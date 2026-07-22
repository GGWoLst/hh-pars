import httpx

from src.config import settings

HH_API_BASE = "https://api.hh.ru"


class HHClient:
    """Тонкий клиент к API hh.ru (https://api.hh.ru/openapi/redoc)."""

    def __init__(self) -> None:
        headers = {"User-Agent": settings.hh_user_agent}
        if settings.hh_access_token:
            headers["Authorization"] = f"Bearer {settings.hh_access_token}"
        self._client = httpx.AsyncClient(base_url=HH_API_BASE, headers=headers, timeout=15)

    async def search_vacancies(
        self,
        text: str = "",
        area: str = "",
        page: int = 0,
        per_page: int = 20,
    ) -> dict:
        params = {
            "text": text or settings.hh_search_text,
            "area": area or settings.hh_search_area,
            "page": page,
            "per_page": per_page,
        }
        response = await self._client.get("/vacancies", params=params)
        response.raise_for_status()
        return response.json()

    async def get_vacancy(self, vacancy_id: str) -> dict:
        response = await self._client.get(f"/vacancies/{vacancy_id}")
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()
