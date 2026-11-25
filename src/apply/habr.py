"""Отклики на Хабр Карьере с cookies сессии владельца (remember_user_token, _career_session).

API соискателя у Хабра нет, поэтому бот ходит в тот же JSON-API, что фронтенд сайта:
CSRF-токен — GET /api/frontend_v1/users/authenticity_token, отклик —
POST /api/frontend/vacancies/<id>/responses {"body": письмо}. Что сайт покажет на
странице вакансии (вошёл ли владелец, вопросы работодателя, заглушка вместо формы) —
из её SSR-состояния (<script data-ssr-state>).
"""

import json
import logging
import re

import httpx

from src.apply.common import (
    ApplyResult,
    ApplyStatus,
    SessionExpired,
    account_client,
    jar_to_dict,
    response_json,
    short,
)

logger = logging.getLogger(__name__)

HABR_BASE_URL = "https://career.habr.com"
TOKEN_URL = f"{HABR_BASE_URL}/api/frontend_v1/users/authenticity_token"
VACANCIES_API_URL = f"{HABR_BASE_URL}/api/frontend/vacancies"

_SSR_STATE_RE = re.compile(r'<script[^>]*data-ssr-state="true"[^>]*>(.*?)</script>', re.S)


def parse_ssr_state(html: str) -> dict:
    match = _SSR_STATE_RE.search(html)
    if match is None:
        return {}
    try:
        state = json.loads(match.group(1))
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def login_name(state: dict) -> str | None:
    """Логин владельца из SSR-состояния страницы вакансии; None — гость."""
    login = state.get("userLogin")
    if isinstance(login, dict):
        login = login.get("login") or login.get("name") or "вход есть"
    return str(login) if login else None


def classify_response(status_code: int, payload: dict | None, text: str) -> ApplyResult:
    if 200 <= status_code < 300:
        return ApplyResult(ApplyStatus.SENT)
    blob = json.dumps(payload, ensure_ascii=False) if payload else text[:500]
    lowered = blob.lower()
    if "captcha" in lowered or "капч" in lowered:
        return ApplyResult(ApplyStatus.MANUAL, "Хабр просит пройти капчу")
    if "already" in lowered or "уже" in lowered:
        return ApplyResult(ApplyStatus.ALREADY, "отклик уже был")
    if status_code in (401, 403):
        return ApplyResult(ApplyStatus.SESSION_EXPIRED, f"Хабр не принял вход (HTTP {status_code})")
    if status_code == 404:
        return ApplyResult(ApplyStatus.MANUAL, "вакансия недоступна")
    return ApplyResult(ApplyStatus.ERROR, f"Хабр: HTTP {status_code} {short(blob, 150)}")


class HabrAccount:
    def __init__(
        self, cookies: dict[str, str], transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = account_client(cookies, transport)

    async def __aenter__(self) -> "HabrAccount":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._client.aclose()

    @property
    def cookies(self) -> dict[str, str]:
        return jar_to_dict(self._client.cookies)

    async def _vacancy_page(self, habr_id: str) -> httpx.Response:
        response = await self._client.get(f"{HABR_BASE_URL}/vacancies/{habr_id}")
        if response.is_redirect:
            raise SessionExpired(f"Хабр перенаправил на {response.headers.get('location')}")
        return response

    async def whoami(self) -> str:
        """Логин владельца на Хабре; SessionExpired, если cookies не дают входа."""
        listing = await self._client.get(
            VACANCIES_API_URL, params={"type": "all", "sort": "date", "page": 1}
        )
        listing.raise_for_status()
        items = (response_json(listing) or {}).get("list") or []
        if not items:
            raise httpx.HTTPError("Хабр не вернул ни одной вакансии для проверки входа")

        page = await self._vacancy_page(str(items[0]["id"]))
        page.raise_for_status()
        name = login_name(parse_ssr_state(page.text))
        if name is None:
            raise SessionExpired("Хабр не признал вход — сайт видит гостя")
        return name

    async def apply(self, habr_id: str, letter: str) -> ApplyResult:
        page_url = f"{HABR_BASE_URL}/vacancies/{habr_id}"
        try:
            page = await self._vacancy_page(habr_id)
        except SessionExpired as exc:
            return ApplyResult(ApplyStatus.SESSION_EXPIRED, str(exc))
        if page.status_code == 404:
            return ApplyResult(ApplyStatus.MANUAL, "вакансия снята с публикации")
        page.raise_for_status()

        state = parse_ssr_state(page.text)
        vacancy = state.get("vacancy") or {}
        placeholder = state.get("placeholder") or {}
        logger.info(
            "Хабр: вакансия %s — вход=%s, response.kind=%s, placeholder=%r, prescreening=%s, "
            "responses=%s, createResponse=%s",
            habr_id,
            login_name(state) is not None,
            (vacancy.get("response") or {}).get("kind"),
            placeholder.get("title"),
            bool(state.get("prescreening")),
            type(state.get("responses")).__name__,
            sorted(state["createResponse"])
            if isinstance(state.get("createResponse"), dict)
            else None,
        )

        if login_name(state) is None:
            return ApplyResult(
                ApplyStatus.SESSION_EXPIRED, "Хабр не признал вход — сайт видит гостя"
            )
        if vacancy.get("archived"):
            return ApplyResult(ApplyStatus.MANUAL, "вакансия в архиве")
        if isinstance(state.get("responses"), list) and state["responses"]:
            return ApplyResult(ApplyStatus.ALREADY, "отклик уже был")
        if state.get("prescreening"):
            return ApplyResult(ApplyStatus.MANUAL, "работодатель просит ответить на вопросы")
        if placeholder:
            # Вместо формы отклика сайт показывает заглушку — пересказываем её.
            text = short(f"{placeholder.get('title', '')}. {placeholder.get('description', '')}")
            if "уже" in text.lower():
                return ApplyResult(ApplyStatus.ALREADY, text)
            return ApplyResult(ApplyStatus.MANUAL, f"Хабр: {text}")

        token_response = await self._client.get(TOKEN_URL, headers={"Accept": "application/json"})
        token_response.raise_for_status()
        token = (response_json(token_response) or {}).get("token")
        if not token:
            return ApplyResult(ApplyStatus.ERROR, "Хабр не выдал CSRF-токен")

        response = await self._client.post(
            f"{VACANCIES_API_URL}/{habr_id}/responses",
            json={"body": letter},
            headers={
                "X-Csrf-Token": token,
                "Accept": "application/json",
                "Referer": page_url,
                "Origin": HABR_BASE_URL,
            },
        )
        payload = response_json(response)
        logger.info(
            "Хабр: отклик на %s — HTTP %s, ключи %s",
            habr_id,
            response.status_code,
            sorted(payload or {})[:20],
        )
        return classify_response(response.status_code, payload, response.text)
