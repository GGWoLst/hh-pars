import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.bot.handlers import router
from src.config import settings
from src.parser import fetch_new_vacancies
from src.storage.db import init_models

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


async def notify_new_vacancies(bot: Bot) -> None:
    vacancies = await fetch_new_vacancies()
    if not vacancies or not settings.telegram_chat_id:
        return

    for vacancy in vacancies:
        await bot.send_message(
            settings.telegram_chat_id,
            f"{vacancy.name} — {vacancy.employer}\n{vacancy.url}",
        )


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    await init_models()

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        notify_new_vacancies,
        "interval",
        minutes=settings.parse_interval_minutes,
        args=[bot],
    )
    scheduler.start()

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
