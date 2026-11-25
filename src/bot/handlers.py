from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot.keyboards import MAIN_MENU_CHECK_NOW, main_menu_kb
from src.config import settings
from src.parser import (
    check_new_vacancies_for_user,
    format_vacancy,
    send_vacancy,
    vacancy_markup,
)
from src.storage.db import get_session
from src.storage.models import User

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if user is None:
            session.add(User(id=message.from_user.id, chat_id=message.chat.id))
            await session.commit()

    await message.answer(
        "Привет! Я бот-парсер вакансий hh.ru и Хабр Карьеры.\n\n"
        "Заведи пресет мониторинга (профессия, стек, грейд, регион) — буду проверять "
        "новые вакансии по нему и присылать сюда. Плюс можно выгрузить всё найденное в Excel.",
        reply_markup=main_menu_kb(owner=settings.is_owner(message.from_user.id)),
    )


@router.message(lambda m: m.text == MAIN_MENU_CHECK_NOW)
async def cmd_check_now(message: Message) -> None:
    results = await check_new_vacancies_for_user(message.from_user.id)

    if not results:
        await message.answer(
            "У тебя пока нет пресетов мониторинга — добавь через «➕ Новый пресет»."
        )
        return

    found_any = False
    for preset, new_items in results:
        for item, record in new_items:
            found_any = True
            await send_vacancy(
                message.bot,
                message.chat.id,
                format_vacancy(item, preset),
                reply_markup=vacancy_markup(preset, record),
            )

    if not found_any:
        await message.answer("Новых вакансий по твоим пресетам не найдено.")
