import json
from dataclasses import dataclass
from enum import StrEnum

import httpx
from cryptography.fernet import Fernet, InvalidToken

from src.config import settings


class ApplyStatus(StrEnum):
    SENT = "sent"
    ALREADY = "already"
    MANUAL = "manual"  # бот не может: вопросы работодателя, вакансия закрыта и т.п.
    SESSION_EXPIRED = "session_expired"
    LIMIT = "limit"
    ERROR = "error"


# Итоговые статусы: решение записывается, кнопки под вакансией убираются.
# Остальные можно повторить (после нового входа, завтра, после сбоя сети).
FINAL_STATUSES = {ApplyStatus.SENT, ApplyStatus.ALREADY, ApplyStatus.MANUAL}


@dataclass
class ApplyResult:
    status: ApplyStatus
    detail: str = ""


class SessionExpired(Exception):
    """Сайт не признаёт cookies: вход истёк или прислали не те."""


class CookieError(ValueError):
    """Не удалось разобрать присланные cookies."""


def parse_cookies(text: str, domain: str) -> dict[str, str]:
    """Cookies сайта из того, что владелец скопировал из браузера.

    Понимает строку заголовка Cookie («a=1; b=2»), JSON-экспорт расширений
    (Cookie-Editor, EditThisCookie) и cookies.txt (формат Netscape). Cookies
    чужих доменов из экспорта отбрасываются.
    """
    text = text.strip().lstrip("﻿")
    if not text:
        raise CookieError("пустое сообщение")

    if text[0] in "[{":
        pairs = _from_json(text, domain)
    elif "\t" in text:
        pairs = _from_netscape(text, domain)
    else:
        pairs = _from_header(text)

    cookies = {name: value for name, value in pairs if name}
    if not cookies:
        raise CookieError(f"не нашёл cookies для {domain}")
    return cookies


def _domain_matches(cookie_domain: str | None, domain: str) -> bool:
    if not cookie_domain:
        return True
    host = cookie_domain.lstrip(".").lower()
    return host == domain or host.endswith("." + domain)


def _from_json(text: str, domain: str) -> list[tuple[str, str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CookieError("похоже на JSON, но не разбирается") from exc

    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        data = data["cookies"]
    if isinstance(data, dict):  # {"имя": "значение"}
        return [(str(k), str(v)) for k, v in data.items() if isinstance(v, str | int)]
    if not isinstance(data, list):
        raise CookieError("в JSON нет списка cookies")

    pairs = []
    for entry in data:
        if isinstance(entry, dict) and "name" in entry and "value" in entry:
            if _domain_matches(entry.get("domain"), domain):
                pairs.append((str(entry["name"]), str(entry["value"])))
    return pairs


def _from_netscape(text: str, domain: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        elif not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 7 and _domain_matches(fields[0], domain):
            pairs.append((fields[5], fields[6]))
    return pairs


def _from_header(text: str) -> list[tuple[str, str]]:
    if text[:7].lower() == "cookie:":
        text = text[7:]
    pairs = []
    for part in text.replace("\n", ";").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep:
            pairs.append((name.strip(), value.strip()))
    return pairs


def _fernet() -> Fernet:
    if not settings.session_encryption_key:
        raise RuntimeError("SESSION_ENCRYPTION_KEY не задан")
    return Fernet(settings.session_encryption_key)


def encryption_ready() -> bool:
    try:
        _fernet()
    except (RuntimeError, ValueError):
        return False
    return True


def encrypt_cookies(cookies: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(cookies).encode()).decode()


def decrypt_cookies(token: str) -> dict[str, str]:
    """Расшифровывает cookies; SessionExpired, если ключ сменился или данные битые."""
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except (InvalidToken, RuntimeError, ValueError) as exc:
        raise SessionExpired("сохранённый вход не расшифровать — подключите заново") from exc


def render_letter(template: str, vacancy: str, company: str | None) -> str:
    return template.replace("{вакансия}", vacancy).replace("{компания}", company or "").strip()


def account_client(
    cookies: dict[str, str], transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """HTTP-клиент от имени владельца: его cookies, браузерный User-Agent, RU-прокси.

    Редиректы не выполняются: редирект на вход — это признак истёкшей сессии, а
    ходить с cookies на чужие хосты незачем.
    """
    options: dict = {
        "headers": {
            "User-Agent": settings.browser_user_agent,
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
        "cookies": cookies,
        "timeout": 20,
        "follow_redirects": False,
    }
    if transport is not None:
        options["transport"] = transport
    else:
        options["proxy"] = settings.hh_proxy_url or None
    return httpx.AsyncClient(**options)


def jar_to_dict(cookies: httpx.Cookies) -> dict[str, str]:
    """Текущие cookies клиента: присланные владельцем и обновлённые сайтом поверх."""
    result: dict[str, str] = {}
    # У присланных домена нет, у выставленных сайтом есть — они свежее, идут последними.
    for cookie in sorted(cookies.jar, key=lambda c: bool(c.domain)):
        if cookie.value is not None:
            result[cookie.name] = cookie.value
    return result


def response_json(response: httpx.Response) -> dict | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def short(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
