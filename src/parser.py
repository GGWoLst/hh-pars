import logging

from sqlalchemy import select

from src.hh_client import HHClient
from src.storage.db import get_session
from src.storage.models import Vacancy

logger = logging.getLogger(__name__)


async def fetch_new_vacancies() -> list[Vacancy]:
    """Тянет вакансии с hh.ru и возвращает те, которых ещё нет в БД."""
    client = HHClient()
    try:
        data = await client.search_vacancies()
    finally:
        await client.close()

    items = data.get("items", [])
    new_vacancies: list[Vacancy] = []

    async with get_session() as session:
        for item in items:
            exists = await session.scalar(select(Vacancy).where(Vacancy.id == item["id"]))
            if exists:
                continue

            vacancy = Vacancy(
                id=item["id"],
                name=item["name"],
                employer=(item.get("employer") or {}).get("name"),
                url=item["alternate_url"],
            )
            session.add(vacancy)
            new_vacancies.append(vacancy)

        await session.commit()

    logger.info("Найдено новых вакансий: %d", len(new_vacancies))
    return new_vacancies
