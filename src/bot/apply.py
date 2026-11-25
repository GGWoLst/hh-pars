"""Отклики по кнопкам под вакансией и их настройка — только для владельца бота.

Вход на площадки — cookies браузерной сессии владельца: присылает их в чат (сообщение
бот сразу удаляет), бот проверяет вход и хранит cookies зашифрованными (Fernet).
"""

import logging
from html import escape

import httpx
from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.apply.common import (
    FINAL_STATUSES,
    ApplyResult,
    ApplyStatus,
    CookieError,
    SessionExpired,
    decrypt_cookies,
    encrypt_cookies,
    encryption_ready,
    parse_cookies,
    render_letter,
    short,
)
from src.apply.habr import HabrAccount
from src.apply.hh import HHAccount, Resume
from src.bot.keyboards import MAIN_MENU_APPLY, MAIN_MENU_LABELS, cancel_kb
from src.bot.states import ApplyForm
from src.config import settings
from src.sources import HABR, HABR_ID_PREFIX, HH, SOURCE_LABELS, source_of
from src.storage.db import get_session
from src.storage.models import AccountSession, ApplySettings, FoundVacancy, User, VacancyDecision

logger = logging.getLogger(__name__)

router = Router()
# Весь раздел — только владельцу; сообщения остальных идут дальше, в другие роутеры.
router.message.filter(lambda message: settings.is_owner(message.from_user.id))
router.callback_query.filter(lambda callback: settings.is_owner(callback.from_user.id))

COOKIE_DOMAINS = {HH: "hh.ru", HABR: "habr.com"}
COOKIE_SITES = {HH: "hh.ru", HABR: "career.habr.com"}
MAX_COOKIE_FILE_BYTES = 256 * 1024
MAX_LETTER_CHARS = 3000

DECISION_LABELS = {
    "applied": "✅ Отклик отправлен",
    "rejected": "❌ Отклонено",
    "manual": "✋ Откликнуться на сайте",
}

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Вакансии, по которым отклик уже отправляется: защита от двойного нажатия.
_in_progress: set[int] = set()


# --- меню «⚙️ Отклики» ---------------------------------------------------------


@router.message(F.text == MAIN_MENU_APPLY)
async def show_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, keyboard = await _menu(message.from_user.id)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def _menu(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with get_session() as session:
        accounts = {
            account.source: account
            for account in await session.scalars(
                select(AccountSession).where(AccountSession.user_id == user_id)
            )
        }
        prefs = await session.get(ApplySettings, user_id)

    hh, habr = accounts.get(HH), accounts.get(HABR)
    letter = prefs.letter_template if prefs else ""
    lines = ["<b>Отклики от вашего имени</b>", ""]
    if hh is None:
        lines.append("hh.ru: не подключён")
    elif hh.resume_id:
        lines.append(f"hh.ru: ✅ подключён, резюме «{escape(hh.resume_title or hh.resume_id)}»")
    else:
        lines.append("hh.ru: ✅ подключён, ⚠️ резюме не выбрано")
    if habr is None:
        lines.append("Хабр Карьера: не подключена")
    else:
        lines.append(f"Хабр Карьера: ✅ подключена ({escape(habr.account_name or 'вход есть')})")
    if letter:
        lines.append(f"Письмо: «{escape(short(letter, 300))}»")
    else:
        lines.append("Письмо: не задано — отклик без письма")
    lines += ["", "Под новыми вакансиями — «✅ Подтвердить» (отклик) и «❌ Отклонить»."]
    if not encryption_ready():
        lines += ["", "⚠️ На сервере не задан SESSION_ENCRYPTION_KEY — подключить вход нельзя."]

    rows = [
        [
            InlineKeyboardButton(
                text="🔄 Вход hh.ru" if hh else "🔑 Подключить hh.ru",
                callback_data=f"acc:connect:{HH}",
            ),
            InlineKeyboardButton(
                text="🔄 Вход Хабр" if habr else "🔑 Подключить Хабр",
                callback_data=f"acc:connect:{HABR}",
            ),
        ]
    ]
    if hh is not None:
        rows.append([InlineKeyboardButton(text="📄 Резюме hh.ru", callback_data="acc:resumes")])
    rows.append([InlineKeyboardButton(text="✍️ Шаблон письма", callback_data="acc:letter")])
    off = [
        InlineKeyboardButton(
            text=f"Отключить {SOURCE_LABELS[source]}", callback_data=f"acc:off:{source}"
        )
        for source in (HH, HABR)
        if source in accounts
    ]
    if off:
        rows.append(off)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "acc:cancel")
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("acc:off:"))
async def disconnect(callback: CallbackQuery) -> None:
    source = callback.data.removeprefix("acc:off:")
    async with get_session() as session:
        account = await _account(session, callback.from_user.id, source)
        if account is not None:
            await session.delete(account)
            await session.commit()
    await callback.answer(f"{SOURCE_LABELS.get(source, source)}: вход удалён")
    if isinstance(callback.message, Message):
        text, keyboard = await _menu(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# --- подключение по cookies -----------------------------------------------------


@router.callback_query(F.data.startswith("acc:connect:"))
async def ask_cookies(callback: CallbackQuery, state: FSMContext) -> None:
    source = callback.data.removeprefix("acc:connect:")
    if source not in COOKIE_DOMAINS:
        await callback.answer()
        return
    if not encryption_ready():
        await callback.answer("На сервере не задан SESSION_ENCRYPTION_KEY.", show_alert=True)
        return

    await state.set_state(ApplyForm.cookies)
    await state.update_data(source=source)
    site = COOKIE_SITES[source]
    await callback.message.answer(
        f"<b>Подключение: {SOURCE_LABELS[source]}</b>\n\n"
        f"1. Войдите на {site} в браузере на компьютере.\n"
        "2. Скопируйте cookies сайта — любым способом:\n"
        "• расширение Cookie-Editor → Export → <b>Header String</b> "
        "(или JSON — его лучше файлом);\n"
        f"• F12 → Network → обновите страницу → первый запрос к {site} → "
        "Request Headers → <code>Cookie</code> → скопируйте значение.\n"
        "3. Пришлите сюда текстом или файлом .txt/.json.\n\n"
        "Сообщение с cookies сразу удалю из чата. Cookies — это вход в ваш аккаунт: "
        "храню их зашифрованными и использую только для откликов по вашей кнопке.",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_kb(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.message(ApplyForm.cookies)
async def cookies_received(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text in MAIN_MENU_LABELS:
        await state.clear()
        await message.answer("Подключение отменено.")
        return

    source = (await state.get_data()).get("source")
    if source not in COOKIE_DOMAINS:
        await state.clear()
        return

    raw = await _read_payload(message, bot)
    note = (
        ""
        if await _delete(message)
        else "\n\n⚠️ Не смог удалить сообщение с cookies — удалите его сами."
    )
    if raw is None:
        await message.answer(
            "Пришлите cookies текстом или файлом .txt/.json." + note, reply_markup=cancel_kb()
        )
        return
    try:
        cookies = parse_cookies(raw, COOKIE_DOMAINS[source])
    except CookieError as exc:
        await message.answer(
            f"Не разобрал cookies: {exc}. Пришлите ещё раз." + note, reply_markup=cancel_kb()
        )
        return

    status = await message.answer("Проверяю вход…")
    resumes: list[Resume] = []
    account_name = None
    try:
        if source == HH:
            async with HHAccount(cookies) as client:
                resumes = await client.resumes()
                fresh = client.cookies
        else:
            async with HabrAccount(cookies) as client:
                account_name = await client.whoami()
                fresh = client.cookies
    except SessionExpired as exc:
        await status.edit_text(
            f"Вход не принят: {exc}. Войдите на сайт заново и пришлите свежие cookies." + note,
            reply_markup=cancel_kb(),
        )
        return
    except httpx.HTTPError as exc:
        logger.warning("%s: проверка входа не удалась: %r", SOURCE_LABELS[source], exc)
        await status.edit_text(
            f"Не удалось проверить вход — сайт не ответил ({type(exc).__name__}). "
            "Пришлите cookies ещё раз чуть позже." + note,
            reply_markup=cancel_kb(),
        )
        return

    user_id = message.from_user.id
    async with get_session() as session:
        if await session.get(User, user_id) is None:
            session.add(User(id=user_id, chat_id=message.chat.id))
        account = await _account(session, user_id, source)
        if account is None:
            account = AccountSession(user_id=user_id, source=source)
            session.add(account)
        account.cookies = encrypt_cookies(fresh)
        account.account_name = account_name
        if source == HH:
            current = next((r for r in resumes if r.id == account.resume_id), None)
            chosen = current or (resumes[0] if len(resumes) == 1 else None)
            account.resume_id = chosen.id if chosen else None
            account.resume_title = chosen.title if chosen else None
        await session.commit()
    await state.clear()
    logger.info("%s: вход подключён (резюме найдено: %d)", SOURCE_LABELS[source], len(resumes))

    if source == HABR:
        await status.edit_text(f"✅ Хабр Карьера подключена ({account_name})." + note)
    elif account.resume_id:
        more = " Сменить — «📄 Резюме hh.ru» в «⚙️ Отклики»." if len(resumes) > 1 else ""
        await status.edit_text(
            f"✅ hh.ru подключён. Резюме для откликов: «{account.resume_title}».{more}" + note
        )
    elif resumes:
        await status.edit_text("✅ hh.ru подключён. Выберите резюме для откликов:" + note)
        await _offer_resumes(message, state, resumes, None)
    else:
        await status.edit_text(
            "✅ hh.ru подключён, но резюме на странице «Мои резюме» не нашлось. Создайте "
            "резюме на hh.ru и нажмите «📄 Резюме hh.ru» в «⚙️ Отклики»." + note
        )


async def _read_payload(message: Message, bot: Bot) -> str | None:
    if message.text:
        return message.text
    document = message.document
    if document is None or (document.file_size or 0) > MAX_COOKIE_FILE_BYTES:
        return None
    buffer = await bot.download(document)
    return buffer.read().decode("utf-8", errors="replace") if buffer else None


async def _delete(message: Message) -> bool:
    try:
        await message.delete()
    except TelegramAPIError:
        return False
    return True


# --- резюме hh.ru ---------------------------------------------------------------


@router.callback_query(F.data == "acc:resumes")
async def list_resumes(callback: CallbackQuery, state: FSMContext) -> None:
    async with get_session() as session:
        account = await _account(session, callback.from_user.id, HH)
        if account is None:
            await callback.answer("hh.ru не подключён.", show_alert=True)
            return
        try:
            cookies = decrypt_cookies(account.cookies)
            async with HHAccount(cookies) as client:
                resumes = await client.resumes()
                fresh = client.cookies
        except SessionExpired as exc:
            await callback.answer(f"Вход в hh.ru не действует: {exc}", show_alert=True)
            return
        except httpx.HTTPError as exc:
            await callback.answer(f"hh.ru не ответил ({type(exc).__name__}).", show_alert=True)
            return
        if fresh != cookies:
            account.cookies = encrypt_cookies(fresh)
            await session.commit()
        current = account.resume_id

    await callback.answer()
    if not resumes:
        await callback.message.answer("На странице «Мои резюме» hh.ru резюме не нашлось.")
        return
    await _offer_resumes(callback.message, state, resumes, current)


async def _offer_resumes(
    message: Message, state: FSMContext, resumes: list[Resume], current: str | None
) -> None:
    # В callback_data — номер, а не hash: так точно влезает в 64 байта.
    await state.update_data(resumes=[[r.id, r.title] for r in resumes])
    rows = [
        [
            InlineKeyboardButton(
                text=("✔️ " if r.id == current else "") + short(r.title, 60),
                callback_data=f"acc:res:{index}",
            )
        ]
        for index, r in enumerate(resumes)
    ]
    await message.answer(
        "Резюме для откликов на hh.ru:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


@router.callback_query(F.data.startswith("acc:res:"))
async def resume_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    options = (await state.get_data()).get("resumes") or []
    index = int(callback.data.removeprefix("acc:res:"))
    if index >= len(options):
        await callback.answer("Список устарел — откройте «📄 Резюме hh.ru» снова.", show_alert=True)
        return
    resume_id, title = options[index]

    async with get_session() as session:
        account = await _account(session, callback.from_user.id, HH)
        if account is None:
            await callback.answer("hh.ru не подключён.", show_alert=True)
            return
        account.resume_id, account.resume_title = resume_id, title
        await session.commit()

    await callback.answer("Резюме выбрано")
    await callback.message.edit_text(f"Резюме для откликов на hh.ru: «{title}».")


# --- шаблон письма --------------------------------------------------------------


@router.callback_query(F.data == "acc:letter")
async def ask_letter(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ApplyForm.letter)
    await callback.message.answer(
        "Пришлите текст сопроводительного письма одним сообщением. Вместо {вакансия} и "
        "{компания} подставлю название вакансии и компании.\n\n"
        "«-» — откликаться без письма.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ApplyForm.letter)
async def letter_received(message: Message, state: FSMContext) -> None:
    if message.text in MAIN_MENU_LABELS:
        await state.clear()
        await message.answer("Отменено.")
        return
    if not message.text:
        await message.answer("Нужен текст письма.", reply_markup=cancel_kb())
        return

    template = "" if message.text.strip() == "-" else message.text.strip()
    if len(template) > MAX_LETTER_CHARS:
        await message.answer(
            f"Длинновато: {len(template)} символов, можно до {MAX_LETTER_CHARS}.",
            reply_markup=cancel_kb(),
        )
        return

    user_id = message.from_user.id
    async with get_session() as session:
        prefs = await session.get(ApplySettings, user_id)
        if prefs is None:
            prefs = ApplySettings(user_id=user_id)
            session.add(prefs)
        prefs.letter_template = template
        await session.commit()
    await state.clear()

    if not template:
        await message.answer("Письмо выключено — отклики пойдут без него.")
        return
    example = render_letter(template, "Python-разработчик", "ООО «Пример»")
    await message.answer(f"Сохранил. Так оно будет выглядеть:\n\n{example}")


# --- кнопки под вакансией -------------------------------------------------------


@router.callback_query(F.data.startswith("reject:"))
async def reject_vacancy(callback: CallbackQuery) -> None:
    found_id = int(callback.data.removeprefix("reject:"))
    async with get_session() as session:
        vacancy = await _owned_vacancy(session, found_id, callback.from_user.id)
        if vacancy is None:
            await callback.answer("Вакансия не найдена — возможно, пресет удалён.", show_alert=True)
            return
        if vacancy.decision is None:
            session.add(VacancyDecision(found_vacancy_id=vacancy.id, status="rejected"))
            await session.commit()
            label = DECISION_LABELS["rejected"]
        else:
            label = DECISION_LABELS.get(vacancy.decision.status, vacancy.decision.status)

    await callback.answer(label)
    await _mark_message(callback, label, final=True)


@router.callback_query(F.data.startswith("apply:"))
async def apply_vacancy(callback: CallbackQuery) -> None:
    found_id = int(callback.data.removeprefix("apply:"))
    if found_id in _in_progress:
        await callback.answer("Уже отправляю…")
        return
    _in_progress.add(found_id)
    try:
        await _apply(callback, found_id)
    finally:
        _in_progress.discard(found_id)


async def _apply(callback: CallbackQuery, found_id: int) -> None:
    user_id = callback.from_user.id
    async with get_session() as session:
        vacancy = await _owned_vacancy(session, found_id, user_id)
        if vacancy is None:
            await callback.answer("Вакансия не найдена — возможно, пресет удалён.", show_alert=True)
            return
        if vacancy.decision is not None:
            label = DECISION_LABELS.get(vacancy.decision.status, vacancy.decision.status)
            await callback.answer(label)
            await _mark_message(callback, label, final=True)
            return

        source = source_of(vacancy.vacancy_id)
        account = await _account(session, user_id, source)
        if account is None:
            await callback.answer(
                f"Сначала подключите {SOURCE_LABELS[source]}: «{MAIN_MENU_APPLY}».", show_alert=True
            )
            return
        if source == HH and not account.resume_id:
            await callback.answer(
                f"Не выбрано резюме hh.ru: «{MAIN_MENU_APPLY}» → «📄 Резюме hh.ru».",
                show_alert=True,
            )
            return

        prefs = await session.get(ApplySettings, user_id)
        letter = render_letter(
            prefs.letter_template if prefs else "", vacancy.name, vacancy.employer
        )

        await callback.answer("Отправляю отклик…")
        result = await _send_application(account, vacancy, letter)
        logger.info(
            "%s: отклик на %s — %s %s",
            SOURCE_LABELS[source],
            vacancy.vacancy_id,
            result.status,
            result.detail,
        )
        if result.status in FINAL_STATUSES:
            status = "manual" if result.status is ApplyStatus.MANUAL else "applied"
            session.add(
                VacancyDecision(
                    found_vacancy_id=vacancy.id, status=status, detail=result.detail or None
                )
            )
        await session.commit()  # заодно сохраняет обновлённые сайтом cookies

    await _mark_message(
        callback, _result_line(result, source, account), final=result.status in FINAL_STATUSES
    )


async def _send_application(
    account: AccountSession, vacancy: FoundVacancy, letter: str
) -> ApplyResult:
    try:
        cookies = decrypt_cookies(account.cookies)
    except SessionExpired as exc:
        return ApplyResult(ApplyStatus.SESSION_EXPIRED, str(exc))

    try:
        if account.source == HH:
            async with HHAccount(cookies) as client:
                result = await client.apply(vacancy.vacancy_id, account.resume_id, letter)
                fresh = client.cookies
        else:
            habr_id = vacancy.vacancy_id.removeprefix(HABR_ID_PREFIX)
            async with HabrAccount(cookies) as client:
                result = await client.apply(habr_id, letter)
                fresh = client.cookies
    except httpx.HTTPError as exc:
        logger.warning(
            "%s: отклик на %s не отправлен: %r",
            SOURCE_LABELS[account.source],
            vacancy.vacancy_id,
            exc,
        )
        return ApplyResult(ApplyStatus.ERROR, f"сайт не ответил ({type(exc).__name__})")
    except Exception:
        logger.exception("Отклик на %s: ошибка бота", vacancy.vacancy_id)
        return ApplyResult(ApplyStatus.ERROR, "ошибка в боте — подробности в логах")

    if fresh != cookies:
        account.cookies = encrypt_cookies(fresh)
    return result


def _result_line(result: ApplyResult, source: str, account: AccountSession) -> str:
    site = SOURCE_LABELS[source]
    if result.status is ApplyStatus.SENT:
        line = "✅ Отклик отправлен"
        if source == HH and account.resume_title:
            line += f" — резюме «{account.resume_title}»"
        if result.detail:
            line += f"\n⚠️ {result.detail}"
        return line
    if result.status is ApplyStatus.ALREADY:
        return "✅ Отклик уже был"
    if result.status is ApplyStatus.MANUAL:
        return f"✋ {result.detail} — откликнитесь на сайте по ссылке выше"
    if result.status is ApplyStatus.SESSION_EXPIRED:
        return (
            f"🔑 Вход в {site} не действует: {result.detail}. "
            f"Подключите заново: «{MAIN_MENU_APPLY}»"
        )
    if result.status is ApplyStatus.LIMIT:
        return f"⏳ {site}: {result.detail} — попробуйте позже"
    return f"⚠️ Не удалось откликнуться: {result.detail}"


async def _mark_message(callback: CallbackQuery, line: str, final: bool) -> None:
    """Итог — дописать в сообщение о вакансии и убрать кнопки; иначе — ответить рядом."""
    message = callback.message
    if not isinstance(message, Message):  # сообщение слишком старое, бот его не видит
        await callback.bot.send_message(callback.from_user.id, line)
        return
    if final:
        try:
            await message.edit_text(
                f"{message.html_text}\n\n<b>{escape(line)}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
            return
        except TelegramAPIError as exc:
            logger.warning("Не удалось отметить сообщение о вакансии: %r", exc)
    await message.reply(line)


# --- общее ----------------------------------------------------------------------


async def _account(session, user_id: int, source: str) -> AccountSession | None:
    return await session.scalar(
        select(AccountSession).where(
            AccountSession.user_id == user_id, AccountSession.source == source
        )
    )


async def _owned_vacancy(session, found_id: int, user_id: int) -> FoundVacancy | None:
    vacancy = await session.get(
        FoundVacancy,
        found_id,
        options=[selectinload(FoundVacancy.preset), selectinload(FoundVacancy.decision)],
    )
    if vacancy is None or vacancy.preset.user_id != user_id:
        return None
    return vacancy
