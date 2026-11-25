import json
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet

from src.apply.common import (
    ApplyStatus,
    CookieError,
    SessionExpired,
    decrypt_cookies,
    encrypt_cookies,
    encryption_ready,
    parse_cookies,
    render_letter,
)
from src.apply.habr import HabrAccount, login_name, parse_ssr_state
from src.apply.hh import HHAccount, classify_apply_response, parse_resumes
from src.bot.keyboards import MAIN_MENU_APPLY, decision_kb, main_menu_kb
from src.config import settings

HH_COOKIES = {"hhtoken": "token", "_xsrf": "xsrf-1", "hhuid": "uid"}
RESUME = "0123456789abcdef0123456789abcdef012345"


# --- cookies ----------------------------------------------------------------------


def test_parse_header_string_keeps_equals_in_values() -> None:
    assert parse_cookies("Cookie: hhtoken=a==; _xsrf=b ;hhuid=c", "hh.ru") == {
        "hhtoken": "a==",
        "_xsrf": "b",
        "hhuid": "c",
    }


def test_parse_cookie_editor_json_drops_foreign_domains() -> None:
    exported = json.dumps(
        [
            {"domain": ".hh.ru", "name": "hhtoken", "value": "t", "httpOnly": True},
            {"domain": "spb.hh.ru", "name": "region", "value": "2"},
            {"domain": ".google.com", "name": "NID", "value": "g"},
            {"domain": ".hh.ru.evil.com", "name": "x", "value": "y"},
        ]
    )
    assert parse_cookies(exported, "hh.ru") == {"hhtoken": "t", "region": "2"}


def test_parse_json_object_and_habr_domains() -> None:
    assert parse_cookies('{"_career_session": "s"}', "habr.com") == {"_career_session": "s"}
    exported = json.dumps(
        [
            {"domain": "career.habr.com", "name": "_career_session", "value": "s"},
            {"domain": ".habr.com", "name": "remember_user_token", "value": "r"},
        ]
    )
    assert parse_cookies(exported, "habr.com") == {
        "_career_session": "s",
        "remember_user_token": "r",
    }


def test_parse_netscape_with_httponly_lines() -> None:
    text = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.hh.ru\tTRUE\t/\tTRUE\t1999999999\thhtoken\tsecret\n"
        ".hh.ru\tTRUE\t/\tFALSE\t1999999999\t_xsrf\tx\n"
        ".ya.ru\tTRUE\t/\tFALSE\t1999999999\tyandexuid\t1\n"
    )
    assert parse_cookies(text, "hh.ru") == {"hhtoken": "secret", "_xsrf": "x"}


@pytest.mark.parametrize("text", ["", "   ", "просто текст", "[1, 2]", "{bad json"])
def test_parse_rejects_garbage(text: str) -> None:
    with pytest.raises(CookieError):
        parse_cookies(text, "hh.ru")


def test_encryption_roundtrip_and_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "session_encryption_key", "")
    assert not encryption_ready()

    monkeypatch.setattr(settings, "session_encryption_key", Fernet.generate_key().decode())
    assert encryption_ready()
    token = encrypt_cookies(HH_COOKIES)
    assert "token" not in token
    assert decrypt_cookies(token) == HH_COOKIES

    monkeypatch.setattr(settings, "session_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(SessionExpired):
        decrypt_cookies(token)


def test_render_letter() -> None:
    template = "Здравствуйте! Интересна вакансия «{вакансия}» в {компания}."
    assert render_letter(template, "DevOps", "Acme") == (
        "Здравствуйте! Интересна вакансия «DevOps» в Acme."
    )
    assert render_letter("", "DevOps", None) == ""


# --- клавиатуры ---------------------------------------------------------------------


def test_decision_buttons_fit_telegram_limit() -> None:
    markup = decision_kb(2**63 - 1)
    texts = [button.text for button in markup.inline_keyboard[0]]
    assert texts == ["✅ Подтвердить", "❌ Отклонить"]
    assert all(len(b.callback_data.encode()) <= 64 for b in markup.inline_keyboard[0])


def test_apply_menu_only_for_owner() -> None:
    def labels(markup):
        return [button.text for row in markup.keyboard for button in row]

    assert MAIN_MENU_APPLY not in labels(main_menu_kb())
    assert MAIN_MENU_APPLY in labels(main_menu_kb(owner=True))


def test_is_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "owner_telegram_id", 0)
    assert not settings.is_owner(0)
    monkeypatch.setattr(settings, "owner_telegram_id", 42)
    assert settings.is_owner(42)
    assert not settings.is_owner(43)


# --- hh.ru --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (200, {"success": "true", "responseStatus": {}}, ApplyStatus.SENT),
        (200, {"error": "negotiations-limit-exceeded"}, ApplyStatus.LIMIT),
        (400, {"error": "test-required"}, ApplyStatus.MANUAL),
        (400, {"error": "letter-required"}, ApplyStatus.MANUAL),
        (409, {"error": "alreadyApplied"}, ApplyStatus.ALREADY),
        (200, {"type": "need-login"}, ApplyStatus.SESSION_EXPIRED),
        (200, {"success": False}, ApplyStatus.ERROR),
        (403, None, ApplyStatus.ERROR),
        (200, None, ApplyStatus.ERROR),
        (500, {"error": "something-new"}, ApplyStatus.ERROR),
    ],
)
def test_classify_hh_response(status_code: int, payload: dict | None, expected) -> None:
    assert classify_apply_response(status_code, payload).status is expected


def test_parse_resumes_dedupes_links_and_keeps_titles() -> None:
    html = f"""
        <div data-qa="resume"><a href="/resume/{RESUME}"><span>DevOps-инженер</span></a>
          <a href="/resume/{RESUME}?edit=1">Редактировать</a></div>
        <div data-qa="resume"><a href="/resume/{"f" * 38}"></a></div>
        <a href="/resume/new">Создать</a>
    """
    resumes = parse_resumes(html)
    assert [(r.id, r.title) for r in resumes] == [
        (RESUME, "DevOps-инженер"),
        ("f" * 38, "Резюме ffffff"),
    ]


class HHSite:
    """Подставной hh.ru: записывает запросы, отвечает по сценарию."""

    def __init__(self, popup: dict, post: httpx.Response, negotiations: str = "") -> None:
        self.popup, self.post, self.negotiations = popup, post, negotiations
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/applicant/vacancy_response/popup" and request.method == "GET":
            return httpx.Response(200, json=self.popup)
        if path == "/applicant/vacancy_response/popup":
            return self.post
        if path == "/applicant/negotiations":
            return httpx.Response(200, text=self.negotiations)
        return httpx.Response(404)


async def _hh_apply(site: HHSite, cookies: dict = HH_COOKIES) -> tuple:
    async with HHAccount(cookies, transport=httpx.MockTransport(site)) as client:
        result = await client.apply("139556670", RESUME, "Письмо")
        return result, client.cookies


async def test_hh_apply_sends_form_and_confirms_in_negotiations() -> None:
    site = HHSite(
        popup={"type": "popup"},
        post=httpx.Response(
            200,
            json={"success": "true"},
            headers={"Set-Cookie": "_xsrf=xsrf-2; Domain=.hh.ru; Path=/"},
        ),
        negotiations='<a href="/vacancy/139556670">DevOps</a>',
    )
    result, cookies = await _hh_apply(site)

    assert result.status is ApplyStatus.SENT
    assert result.detail == ""
    assert [(r.method, r.url.path) for r in site.requests] == [
        ("GET", "/applicant/vacancy_response/popup"),
        ("POST", "/applicant/vacancy_response/popup"),
        ("GET", "/applicant/negotiations"),
    ]
    post = site.requests[1]
    form = {k: v[0] for k, v in parse_qs(post.content.decode(), keep_blank_values=True).items()}
    assert form["vacancy_id"] == "139556670"
    assert form["resume_hash"] == RESUME
    assert form["letter"] == "Письмо"
    assert form["_xsrf"] == "xsrf-1"
    assert post.headers["X-Xsrftoken"] == "xsrf-1"
    assert "hhtoken=token" in post.headers["Cookie"]
    assert cookies["_xsrf"] == "xsrf-2"  # обновлённую сайтом cookie бот сохранит


async def test_hh_apply_warns_when_not_in_negotiations() -> None:
    site = HHSite({"type": "popup"}, httpx.Response(200, json={"success": "true"}), "пусто")
    result, _ = await _hh_apply(site)
    assert result.status is ApplyStatus.SENT
    assert "не вижу" in result.detail


async def test_hh_apply_stops_when_site_wants_login() -> None:
    site = HHSite({"type": "need-login"}, httpx.Response(500))
    result, _ = await _hh_apply(site)
    assert result.status is ApplyStatus.SESSION_EXPIRED
    assert [r.method for r in site.requests] == ["GET"]  # до отправки отклика не дошло


async def test_hh_apply_reports_test_required() -> None:
    site = HHSite({"type": "popup"}, httpx.Response(400, json={"error": "test-required"}))
    result, _ = await _hh_apply(site)
    assert result.status is ApplyStatus.MANUAL
    assert "вопросы" in result.detail


async def test_hh_apply_needs_xsrf_cookie() -> None:
    site = HHSite({"type": "popup"}, httpx.Response(200, json={"success": "true"}))
    result, _ = await _hh_apply(site, cookies={"hhtoken": "token"})
    assert result.status is ApplyStatus.SESSION_EXPIRED
    assert site.requests == []


async def test_hh_resumes_redirect_to_login_means_expired_session() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://hh.ru/account/login?backurl=x"})

    async with HHAccount(HH_COOKIES, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SessionExpired):
            await client.resumes()


# --- Хабр Карьера -------------------------------------------------------------------


def ssr_page(state: dict) -> str:
    payload = json.dumps(state, ensure_ascii=False)
    return f'<html><script type="application/json" data-ssr-state="true">{payload}</script></html>'


LOGGED_IN = {
    "userLogin": "wolst",
    "vacancy": {"id": 7, "archived": False, "response": {"kind": "quick"}},
    "placeholder": None,
    "prescreening": None,
    "responses": None,
}


def test_ssr_state_and_login() -> None:
    assert login_name(parse_ssr_state(ssr_page(LOGGED_IN))) == "wolst"
    assert login_name(parse_ssr_state(ssr_page({"userLogin": None}))) is None
    assert login_name({"userLogin": {"login": "x"}}) == "x"
    assert parse_ssr_state("<html>нет состояния</html>") == {}


class HabrSite:
    def __init__(self, page: dict | None, post: httpx.Response | None = None) -> None:
        self.page, self.post = page, post
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/vacancies/7":
            if self.page is None:
                return httpx.Response(404)
            return httpx.Response(200, text=ssr_page(self.page))
        if path == "/api/frontend_v1/users/authenticity_token":
            return httpx.Response(200, json={"token": "csrf-1"})
        if path == "/api/frontend/vacancies/7/responses":
            return self.post
        if path == "/api/frontend/vacancies":
            return httpx.Response(200, json={"list": [{"id": 7}]})
        return httpx.Response(404)


async def _habr_apply(site: HabrSite):
    cookies = {"remember_user_token": "r", "_career_session": "s"}
    async with HabrAccount(cookies, transport=httpx.MockTransport(site)) as client:
        return await client.apply("7", "Письмо")


async def test_habr_apply_posts_letter_with_csrf() -> None:
    site = HabrSite(LOGGED_IN, httpx.Response(201, json={"id": 555}))
    result = await _habr_apply(site)

    assert result.status is ApplyStatus.SENT
    post = site.requests[-1]
    assert post.method == "POST"
    assert json.loads(post.content) == {"body": "Письмо"}
    assert post.headers["X-Csrf-Token"] == "csrf-1"
    assert "remember_user_token=r" in post.headers["Cookie"]


@pytest.mark.parametrize(
    ("page", "expected", "detail_part"),
    [
        ({**LOGGED_IN, "userLogin": None}, ApplyStatus.SESSION_EXPIRED, "гостя"),
        ({**LOGGED_IN, "prescreening": {"questions": [1]}}, ApplyStatus.MANUAL, "вопросы"),
        ({**LOGGED_IN, "vacancy": {"archived": True}}, ApplyStatus.MANUAL, "архив"),
        (
            {**LOGGED_IN, "placeholder": {"title": "Заполните профиль", "description": "…"}},
            ApplyStatus.MANUAL,
            "Заполните профиль",
        ),
        ({**LOGGED_IN, "responses": [{"id": 1}]}, ApplyStatus.ALREADY, ""),
        (None, ApplyStatus.MANUAL, "снята"),
    ],
)
async def test_habr_apply_checks_page_before_posting(page, expected, detail_part) -> None:
    site = HabrSite(page)
    result = await _habr_apply(site)
    assert result.status is expected
    assert detail_part in result.detail
    assert all(r.method == "GET" for r in site.requests)  # отклик не отправлялся


async def test_habr_apply_maps_already_responded_error() -> None:
    site = HabrSite(LOGGED_IN, httpx.Response(422, json={"errors": ["Вы уже откликнулись"]}))
    assert (await _habr_apply(site)).status is ApplyStatus.ALREADY


async def test_habr_whoami() -> None:
    cookies = {"remember_user_token": "r"}
    async with HabrAccount(cookies, transport=httpx.MockTransport(HabrSite(LOGGED_IN))) as c:
        assert await c.whoami() == "wolst"
    guest = HabrSite({"userLogin": None})
    async with HabrAccount(cookies, transport=httpx.MockTransport(guest)) as c:
        with pytest.raises(SessionExpired):
            await c.whoami()
