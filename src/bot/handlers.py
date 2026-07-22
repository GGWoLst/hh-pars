from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.parser import fetch_new_vacancies

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот-парсер вакансий hh.ru.\n"
        "Команды:\n"
        "/search — проверить новые вакансии прямо сейчас"
    )


@router.message(lambda m: m.text == "/search")
async def cmd_search(message: Message) -> None:
    vacancies = await fetch_new_vacancies()
    if not vacancies:
        await message.answer("Новых вакансий не найдено.")
        return

    for vacancy in vacancies:
        await message.answer(f"{vacancy.name} — {vacancy.employer}\n{vacancy.url}")
