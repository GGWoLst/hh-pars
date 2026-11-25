import asyncio
import logging
from datetime import UTC, datetime, timedelta
from html import escape

import httpx
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot.keyboards import decision_kb, habr_query_params, preset_label, preset_query_text
from src.config import settings
from src.habr_client import HabrClient
from src.hh_client import HHClient
from src.sources import HABR, HABR_ID_PREFIX, HH, SOURCE_LABELS, source_of
from src.storage.db import get_session
from src.storage.models import FoundVacancy, SearchPreset

logger = logging.getLogger(__name__)

# Одна и та же вакансия часто висит и на hh.ru, и на Хабре — под разными id.
# Повтор с другой площадки узнаём по названию и компании среди найденного за этот срок.
CROSS_SOURCE_WINDOW = timedelta(days=30)

# Сколько раз пробовать отправить сообщение, если Telegram просит подождать (flood control).
SEND_ATTEMPTS = 3


def format_vacancy(item: dict, preset: SearchPreset) -> str:
    """Текст сообщения о вакансии в HTML-разметке Telegram (отправлять через send_vacancy)."""
    employer = (item.get("employer") or {}).get("name") or "—"
    label = preset_label(preset.profession, preset.stack, preset.experience, preset.area)
    lines = [f"🔎 <b>{escape(label)}</b>", escape(item["name"]), escape(employer)]
    if item.get("salary"):
        lines.append(f"💰 {escape(item['salary'])}")
    lines.append(f"{SOURCE_LABELS[item['source']]}: {escape(item['alternate_url'])}")
    return "\n".join(lines)


# Новая вакансия: как пришла с площадки (для текста) и запись в БД (её id — в кнопках).
NewVacancy = tuple[dict, FoundVacancy]


def vacancy_markup(preset: SearchPreset, record: FoundVacancy) -> InlineKeyboardMarkup | None:
    """Кнопки «Подтвердить / Отклонить» — только в чате владельца бота."""
    return decision_kb(record.id) if settings.is_owner(preset.user_id) else None


async def send_vacancy(
    bot: Bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> bool:
    """Отправляет сообщение о вакансии; ошибки Telegram не прерывают проход.

    Flood control пережидаем и пробуем снова, остальное (бот заблокирован, сбой сети) —
    в лог. Возвращает, ушло ли сообщение.
    """
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            await bot.send_message(
                chat_id, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
            )
            return True
        except TelegramRetryAfter as exc:
            error: TelegramAPIError = exc
            if attempt < SEND_ATTEMPTS:
                await asyncio.sleep(exc.retry_after)
        except TelegramAPIError as exc:
            error = exc
            break

    logger.warning("Telegram: сообщение в чат %s не отправлено: %r", chat_id, error)
    return False


class VacancySources:
    """Клиенты всех площадок на один проход проверки."""

    def __init__(self) -> None:
        self.hh = HHClient()
        self.habr = HabrClient() if settings.habr_enabled else None

    async def __aenter__(self) -> "VacancySources":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.hh.close()
        if self.habr is not None:
            await self.habr.close()

    async def fetch(self, preset: SearchPreset) -> list[dict]:
        """Вакансии по пресету со всех площадок; сбой одной не мешает остальным."""
        items: list[dict] = []
        try:
            data = await self.hh.search_vacancies(
                text=preset_query_text(preset.profession, preset.stack),
                area=preset.area,
                experience=preset.experience,
            )
            items += data["items"]
        except Exception as exc:
            _log_source_error(HH, preset, exc)

        if self.habr is not None:
            param_sets = habr_query_params(
                preset.profession, preset.stack, preset.experience, preset.area
            )
            if param_sets:
                try:
                    items += (await self.habr.search_vacancies(param_sets))["items"]
                except Exception as exc:
                    _log_source_error(HABR, preset, exc)

        return items


def _log_source_error(source: str, preset: SearchPreset, exc: Exception) -> None:
    # Сетевые сбои и ответы 4xx/5xx — одной строкой; прочее — с трейсбеком: это уже
    # похоже на сломанный разбор (площадка поменяла вёрстку или формат ответа).
    logger.warning(
        "%s: пресет %s не проверен: %r",
        SOURCE_LABELS[source],
        preset.id,
        exc,
        exc_info=not isinstance(exc, httpx.HTTPError),
    )


def _dedup_key(name: str, employer: str | None) -> tuple[str, str] | None:
    if not employer:
        return None
    return " ".join(name.casefold().split()), " ".join(employer.casefold().split())


async def _sources_seen(session, preset_id: int) -> set[str]:
    """Площадки, с которых по пресету уже что-то находили."""
    is_habr = FoundVacancy.vacancy_id.startswith(HABR_ID_PREFIX)
    flags = await session.scalars(
        select(is_habr).where(FoundVacancy.preset_id == preset_id).distinct()
    )
    return {HABR if flag else HH for flag in flags}


async def _find_new_vacancies(
    session, sources: VacancySources, preset: SearchPreset
) -> list[NewVacancy]:
    """Тянет вакансии по пресету, сохраняет новые и возвращает те, о которых надо сообщить."""
    items = await sources.fetch(preset)
    if not items:
        return []

    by_preset = FoundVacancy.preset_id == preset.id
    known_ids = set(
        await session.scalars(
            select(FoundVacancy.vacancy_id).where(
                by_preset, FoundVacancy.vacancy_id.in_([item["id"] for item in items])
            )
        )
    )

    sources_by_key: dict[tuple[str, str], set[str]] = {}
    recent = await session.execute(
        select(FoundVacancy.vacancy_id, FoundVacancy.name, FoundVacancy.employer).where(
            by_preset, FoundVacancy.found_at >= datetime.now(UTC) - CROSS_SOURCE_WINDOW
        )
    )
    for vacancy_id, name, employer in recent:
        key = _dedup_key(name, employer)
        if key is not None:
            sources_by_key.setdefault(key, set()).add(source_of(vacancy_id))

    # Пресет заведён до подключения площадки — её первую выдачу сохраняем молча (она
    # попадёт в Excel-отчёт), иначе на пользователя разом высыпется вся её лента.
    # У нового пресета истории нет — ему присылаем всё, как раньше.
    seen_sources = await _sources_seen(session, preset.id)
    silent: dict[str, int] = {}

    new_items = []
    for item in items:
        if item["id"] in known_ids:
            continue

        source = item["source"]
        employer = (item.get("employer") or {}).get("name")
        key = _dedup_key(item["name"], employer)
        seen_on = sources_by_key.setdefault(key, set()) if key is not None else set()
        if seen_on - {source}:
            continue  # эту вакансию уже прислали с другой площадки
        seen_on.add(source)
        known_ids.add(item["id"])

        record = FoundVacancy(
            preset_id=preset.id,
            vacancy_id=item["id"],
            name=item["name"],
            employer=employer,
            url=item["alternate_url"],
        )
        session.add(record)
        if seen_sources and source not in seen_sources:
            silent[source] = silent.get(source, 0) + 1
            continue
        new_items.append((item, record))

    for source, count in silent.items():
        logger.info(
            "%s: пресет %s — первая выдача площадки, %d вакансий сохранено без рассылки",
            SOURCE_LABELS[source],
            preset.id,
            count,
        )

    return new_items


async def check_new_vacancies_for_all_users(bot: Bot) -> None:
    """Планировщик: проходит по всем активным пресетам всех пользователей и рассылает новинки."""
    async with get_session() as session:
        presets = (
            await session.scalars(
                select(SearchPreset)
                .options(selectinload(SearchPreset.user))
                .where(SearchPreset.is_active.is_(True))
            )
        ).all()

        async with VacancySources() as sources:
            for preset in presets:
                new_items = await _find_new_vacancies(session, sources, preset)
                # Фиксируем найденное до рассылки и по каждому пресету: если проход
                # оборвётся дальше, повторно эти вакансии никому не придут.
                await session.commit()
                for item, record in new_items:
                    await send_vacancy(
                        bot,
                        preset.user.chat_id,
                        format_vacancy(item, preset),
                        reply_markup=vacancy_markup(preset, record),
                    )

    logger.info("Проверка вакансий по всем пресетам завершена")


async def check_new_vacancies_for_user(
    user_id: int,
) -> list[tuple[SearchPreset, list[NewVacancy]]]:
    """Ручная проверка по кнопке: только активные пресеты конкретного пользователя."""
    async with get_session() as session:
        presets = (
            await session.scalars(
                select(SearchPreset).where(
                    SearchPreset.user_id == user_id, SearchPreset.is_active.is_(True)
                )
            )
        ).all()

        result: list[tuple[SearchPreset, list[NewVacancy]]] = []
        async with VacancySources() as sources:
            for preset in presets:
                new_items = await _find_new_vacancies(session, sources, preset)
                result.append((preset, new_items))

        await session.commit()

    return result
