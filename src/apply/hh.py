"""Отклики на hh.ru через веб-интерфейс сайта, с cookies браузерной сессии владельца.

API соискателя (POST api.hh.ru/negotiations) нам закрыт: OAuth-приложение физлицу
не дают. Поэтому бот делает то же, что кнопка «Откликнуться» на сайте:
GET /applicant/vacancy_response/popup — открыть окно отклика (гостю сайт отвечает
{"type": "need-login"}), POST туда же — отправить отклик. Поля формы восстановлены
по веб-интерфейсу, поэтому после «успеха» отклик ищется в списке откликов владельца.
"""

import json
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

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

HH_BASE_URL = "https://hh.ru"
POPUP_URL = f"{HH_BASE_URL}/applicant/vacancy_response/popup"
RESUMES_URL = f"{HH_BASE_URL}/applicant/resumes"
NEGOTIATIONS_URL = f"{HH_BASE_URL}/applicant/negotiations"

_RESUME_HREF_RE = re.compile(r"^/resume/([0-9a-f]{20,})")
_LOGIN_PATHS = ("/account/login", "/account/signup")

# Коды ошибок hh.ru (поле error ответа) → что сказать владельцу. Сверяются по подстроке.
_ERROR_KINDS: list[tuple[tuple[str, ...], ApplyStatus, str]] = [
    (("need-login", "unauthorized"), ApplyStatus.SESSION_EXPIRED, "hh.ru просит войти"),
    (("limit",), ApplyStatus.LIMIT, "лимит откликов на сегодня исчерпан"),
    (("already",), ApplyStatus.ALREADY, "отклик уже был"),
    (("test",), ApplyStatus.MANUAL, "работодатель просит ответить на вопросы"),
    (("letter",), ApplyStatus.MANUAL, "работодатель требует сопроводительное письмо"),
    (
        ("archiv", "not-found", "not_found", "closed", "unavailable"),
        ApplyStatus.MANUAL,
        "вакансия закрыта или в архиве",
    ),
]


@dataclass
class Resume:
    id: str
    title: str


def parse_resumes(html: str) -> list[Resume]:
    """Резюме со страницы «Мои резюме»: ссылки /resume/<hash>, подпись — текст ссылки."""
    soup = BeautifulSoup(html, "lxml")
    titles: dict[str, str] = {}
    for link in soup.select('a[href^="/resume/"]'):
        match = _RESUME_HREF_RE.match(link.get("href", ""))
        if match is None:
            continue
        title = " ".join(link.stripped_strings)
        if not titles.get(match.group(1)):
            titles[match.group(1)] = title
    return [Resume(rid, title or f"Резюме {rid[:6]}") for rid, title in titles.items()]


def _error_code(payload: dict | None) -> str | None:
    if payload is None:
        return None
    for key in ("error", "errors", "errorCode", "code"):
        value = payload.get(key)
        if value:
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if payload.get("type") == "need-login":
        return "need-login"
    if payload.get("success") in (False, "false"):
        return "success=false"
    return None


def classify_apply_response(status_code: int, payload: dict | None) -> ApplyResult:
    code = _error_code(payload)
    if code is None and 200 <= status_code < 300 and payload is not None:
        return ApplyResult(ApplyStatus.SENT)

    code = code or f"HTTP {status_code}"
    lowered = code.lower()
    for markers, status, message in _ERROR_KINDS:
        if any(marker in lowered for marker in markers):
            return ApplyResult(status, message)
    if status_code == 403:
        return ApplyResult(ApplyStatus.ERROR, "hh.ru ответил 403 — возможно, проверка на робота")
    return ApplyResult(ApplyStatus.ERROR, f"hh.ru: {short(code, 150)}")


class HHAccount:
    def __init__(
        self, cookies: dict[str, str], transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = account_client(cookies, transport)

    async def __aenter__(self) -> "HHAccount":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._client.aclose()

    @property
    def cookies(self) -> dict[str, str]:
        return jar_to_dict(self._client.cookies)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        response = await self._client.request(method, url, **kwargs)
        if response.is_redirect:
            location = response.headers.get("location", "")
            if any(path in location for path in _LOGIN_PATHS):
                raise SessionExpired("hh.ru просит войти")
        return response

    async def resumes(self) -> list[Resume]:
        """Резюме владельца; SessionExpired, если cookies не дают входа."""
        response = await self._request("GET", RESUMES_URL)
        if response.status_code == 403:
            raise SessionExpired("hh.ru ответил 403: вход не принят или проверка на робота")
        if response.is_redirect:
            raise SessionExpired(f"hh.ru перенаправил на {response.headers.get('location')}")
        response.raise_for_status()
        return parse_resumes(response.text)

    async def apply(self, vacancy_id: str, resume_id: str, letter: str) -> ApplyResult:
        xsrf = self.cookies.get("_xsrf")
        if not xsrf:
            return ApplyResult(
                ApplyStatus.SESSION_EXPIRED, "в cookies нет _xsrf — пришлите все cookies hh.ru"
            )
        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": xsrf,
            "Referer": f"{HH_BASE_URL}/vacancy/{vacancy_id}",
        }
        try:
            popup = await self._request(
                "GET",
                POPUP_URL,
                params={
                    "vacancyId": vacancy_id,
                    "isTest": "no",
                    "withoutTest": "no",
                    "lux": "true",
                },
                headers=headers,
            )
            info = response_json(popup) or {}
            logger.info(
                "hh.ru: окно отклика на %s — HTTP %s, type=%s, ключи %s",
                vacancy_id,
                popup.status_code,
                info.get("type"),
                sorted(info)[:20],
            )
            if info.get("type") == "need-login":
                return ApplyResult(ApplyStatus.SESSION_EXPIRED, "hh.ru просит войти")

            response = await self._request(
                "POST",
                POPUP_URL,
                data={
                    "_xsrf": xsrf,
                    "vacancy_id": vacancy_id,
                    "resume_hash": resume_id,
                    "ignore_postponed": "true",
                    "incomplete": "false",
                    "mark_applicant_visible_in_vacancy_country": "false",
                    "letter": letter,
                    "lux": "true",
                    "withoutTest": "no",
                    "hhtmFromLabel": "",
                    "hhtmSourceLabel": "",
                },
                headers={**headers, "Origin": HH_BASE_URL},
            )
        except SessionExpired as exc:
            return ApplyResult(ApplyStatus.SESSION_EXPIRED, str(exc))

        payload = response_json(response)
        logger.info(
            "hh.ru: отклик на %s — HTTP %s, ключи %s, error=%s",
            vacancy_id,
            response.status_code,
            sorted(payload or {})[:20],
            _error_code(payload),
        )
        result = classify_apply_response(response.status_code, payload)
        if result.status is ApplyStatus.SENT:
            seen = await self._in_negotiations(vacancy_id)
            if seen is False:
                result.detail = (
                    "hh.ru ответил успехом, но в списке откликов вакансию не вижу — проверьте"
                )
        return result

    async def _in_negotiations(self, vacancy_id: str) -> bool | None:
        """Есть ли вакансия в списке откликов владельца; None — проверить не удалось."""
        try:
            response = await self._request("GET", NEGOTIATIONS_URL)
        except (httpx.HTTPError, SessionExpired):
            return None
        if response.status_code != 200:
            return None
        return re.search(rf"(?<!\d){re.escape(vacancy_id)}(?!\d)", response.text) is not None
