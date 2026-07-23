import logging

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot.keyboards import preset_label, preset_query_text
from src.hh_client import HHClient
from src.storage.db import get_session
from src.storage.models import FoundVacancy, SearchPreset

logger = logging.getLogger(__name__)


def format_vacancy(item: dict, preset: SearchPreset) -> str:
    employer = (item.get("employer") or {}).get("name") or "—"
    label = preset_label(preset.profession, preset.stack, preset.experience, preset.area)
    return f"🔎 <b>{label}</b>\n{item['name']}\n{employer}\n{item['alternate_url']}"


async def _find_new_vacancies(session, client: HHClient, preset: SearchPreset) -> list[dict]:
    """Тянет вакансии по параметрам пресета и возвращает те, что ещё не были найдены."""
    text = preset_query_text(preset.profession, preset.stack)
    data = await client.search_vacancies(text=text, area=preset.area, experience=preset.experience)
    items = data.get("items", [])
    new_items = []

    for item in items:
        already_found = await session.scalar(
            select(FoundVacancy).where(
                FoundVacancy.preset_id == preset.id, FoundVacancy.vacancy_id == item["id"]
            )
        )
        if already_found:
            continue

        session.add(
            FoundVacancy(
                preset_id=preset.id,
                vacancy_id=item["id"],
                name=item["name"],
                employer=(item.get("employer") or {}).get("name"),
                url=item["alternate_url"],
            )
        )
        new_items.append(item)

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

        client = HHClient()
        try:
            for preset in presets:
                new_items = await _find_new_vacancies(session, client, preset)
                for item in new_items:
                    await bot.send_message(preset.user.chat_id, format_vacancy(item, preset))
        finally:
            await client.close()

        await session.commit()

    logger.info("Проверка вакансий по всем пресетам завершена")


async def check_new_vacancies_for_user(user_id: int) -> list[tuple[SearchPreset, list[dict]]]:
    """Ручная проверка по кнопке: только активные пресеты конкретного пользователя."""
    async with get_session() as session:
        presets = (
            await session.scalars(
                select(SearchPreset).where(
                    SearchPreset.user_id == user_id, SearchPreset.is_active.is_(True)
                )
            )
        ).all()

        client = HHClient()
        result: list[tuple[SearchPreset, list[dict]]] = []
        try:
            for preset in presets:
                new_items = await _find_new_vacancies(session, client, preset)
                result.append((preset, new_items))
        finally:
            await client.close()

        await session.commit()

    return result
