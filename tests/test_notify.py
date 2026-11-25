from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from src.config import settings
from src.parser import format_vacancy, send_vacancy, vacancy_markup
from src.storage.models import FoundVacancy, SearchPreset

PRESET = SearchPreset(profession="backend", stack="cpp", experience=None, area="1")
METHOD = SendMessage(chat_id=1, text="test")


class FakeBot:
    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls: list[dict] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.calls.append({"chat_id": chat_id, "text": text, **kwargs})
        if self.errors:
            raise self.errors.pop(0)


def test_format_vacancy_escapes_html_from_sites() -> None:
    item = {
        "id": "1",
        "name": "C++ <Senior> & Lead",
        "employer": {"name": "Рога & Копыта"},
        "alternate_url": "https://hh.ru/vacancy/1",
        "source": "hh",
    }
    assert format_vacancy(item, PRESET) == (
        "🔎 <b>Backend-разработчик · C++ · Любой опыт · Москва</b>\n"
        "C++ &lt;Senior&gt; &amp; Lead\n"
        "Рога &amp; Копыта\n"
        "hh.ru: https://hh.ru/vacancy/1"
    )


async def test_send_vacancy_uses_html_parse_mode() -> None:
    bot = FakeBot()
    assert await send_vacancy(bot, 42, "<b>x</b>") is True
    assert bot.calls == [
        {"chat_id": 42, "text": "<b>x</b>", "parse_mode": ParseMode.HTML, "reply_markup": None}
    ]


async def test_owner_gets_decision_buttons(monkeypatch) -> None:
    monkeypatch.setattr(settings, "owner_telegram_id", 42)
    record = FoundVacancy(id=7, preset_id=1, vacancy_id="1", name="x", url="u")
    owner_preset = SearchPreset(user_id=42, profession="qa", stack="any", area="1")
    other_preset = SearchPreset(user_id=43, profession="qa", stack="any", area="1")

    assert vacancy_markup(other_preset, record) is None
    markup = vacancy_markup(owner_preset, record)
    assert [b.callback_data for b in markup.inline_keyboard[0]] == ["apply:7", "reject:7"]

    bot = FakeBot()
    await send_vacancy(bot, 42, "text", reply_markup=markup)
    assert bot.calls[0]["reply_markup"] is markup


async def test_send_vacancy_waits_out_flood_control() -> None:
    bot = FakeBot(TelegramRetryAfter(METHOD, "Flood control exceeded", retry_after=0))
    assert await send_vacancy(bot, 42, "text") is True
    assert len(bot.calls) == 2


async def test_send_vacancy_gives_up_after_repeated_flood_control() -> None:
    flood = [TelegramRetryAfter(METHOD, "Flood control exceeded", retry_after=0)] * 3
    bot = FakeBot(*flood)
    assert await send_vacancy(bot, 42, "text") is False
    assert len(bot.calls) == 3


async def test_send_vacancy_does_not_raise_when_bot_is_blocked() -> None:
    bot = FakeBot(TelegramForbiddenError(METHOD, "bot was blocked by the user"))
    assert await send_vacancy(bot, 42, "text") is False
    assert len(bot.calls) == 1
