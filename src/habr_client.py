import httpx

from src.config import settings
from src.sources import HABR, HABR_ID_PREFIX

HABR_BASE_URL = "https://career.habr.com"
# Внутренний API страницы /vacancies. Официальный API Хабр Карьеры — только для
# работодателей (отклики и резюме), поиска вакансий в нём нет.
HABR_VACANCIES_URL = f"{HABR_BASE_URL}/api/frontend/vacancies"

QueryParams = list[tuple[str, str | int]]


class HabrClient:
    """Клиент к поиску вакансий Хабр Карьеры (JSON, 25 вакансий на страницу)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        options: dict = {
            "headers": {"User-Agent": settings.hh_user_agent, "Accept": "application/json"},
            "timeout": 15,
            "follow_redirects": True,
        }
        if transport is not None:
            options["transport"] = transport
        else:
            # Через тот же прокси, что и hh.ru: парсинг идёт с RU-ноды, а не с адреса бота.
            options["proxy"] = settings.hh_proxy_url or None
        self._client = httpx.AsyncClient(**options)

    async def search_vacancies(self, param_sets: list[QueryParams]) -> dict:
        """Свежие вакансии по каждому набору фильтров, объединённые без повторов.

        Наборов несколько, когда пресету подходят разные навыки: skills[] Хабр
        объединяет по И, поэтому «JavaScript или TypeScript» — это два запроса.
        """
        items: list[dict] = []
        seen: set[str] = set()
        for filters in param_sets:
            params = [("type", "all"), ("sort", "date"), ("page", 1), *filters]
            response = await self._client.get(HABR_VACANCIES_URL, params=params)
            response.raise_for_status()
            for raw in response.json().get("list", []):
                item = parse_vacancy(raw)
                if item is not None and item["id"] not in seen:
                    seen.add(item["id"])
                    items.append(item)
        return {"items": items}

    async def close(self) -> None:
        await self._client.aclose()


def parse_vacancy(raw: dict) -> dict | None:
    """Вакансия из ответа Хабра в том же виде, что отдаёт HHClient."""
    habr_id = raw.get("id")
    title = raw.get("title")
    if not habr_id or not title:
        return None

    salary = (raw.get("salary") or {}).get("formatted") or None
    return {
        "id": f"{HABR_ID_PREFIX}{habr_id}",
        "name": title,
        "employer": {"name": (raw.get("company") or {}).get("title")},
        "alternate_url": f"{HABR_BASE_URL}/vacancies/{habr_id}",
        "salary": salary,
        "source": HABR,
    }
