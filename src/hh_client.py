import re

import httpx
from bs4 import BeautifulSoup, Tag

from src.config import settings

HH_SEARCH_URL = "https://hh.ru/search/vacancy"

# api.hh.ru отдаёт 403 на анонимные запросы с датацентровых IP, а получить
# доступ для физлица на практике не выходит — поэтому парсим HTML-страницу
# поиска вместо JSON API.
_VACANCY_ID_RE = re.compile(r"/vacancy/(\d+)")


class HHClient:
    """Клиент к hh.ru, парсящий обычную страницу поиска вакансий."""

    def __init__(self) -> None:
        headers = {
            "User-Agent": settings.hh_user_agent,
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        self._client = httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True)

    async def search_vacancies(
        self,
        text: str = "",
        area: str = "",
        page: int = 0,
    ) -> dict:
        params = {
            "text": text or settings.hh_search_text,
            "area": area or settings.hh_search_area,
            "page": page,
        }
        response = await self._client.get(HH_SEARCH_URL, params=params)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        items = []
        for card in soup.select('[data-qa="vacancy-serp__vacancy"]'):
            item = self._parse_card(card)
            if item is not None:
                items.append(item)

        return {"items": items}

    def _parse_card(self, card: Tag) -> dict | None:
        title_link = card.select_one('[data-qa="serp-item__title"]')
        href = title_link.get("href") if title_link else None
        match = _VACANCY_ID_RE.search(href) if href else None
        if title_link is None or match is None:
            return None

        vacancy_id = match.group(1)
        employer_el = card.select_one('[data-qa="vacancy-serp__vacancy-employer-text"]')
        employer_name = " ".join(employer_el.stripped_strings) if employer_el else None

        return {
            "id": vacancy_id,
            "name": " ".join(title_link.stripped_strings),
            "employer": {"name": employer_name},
            "alternate_url": f"https://hh.ru/vacancy/{vacancy_id}",
        }

    async def close(self) -> None:
        await self._client.aclose()
