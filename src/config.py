from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # HH.ru API
    hh_client_id: str = ""
    hh_client_secret: str = ""
    hh_access_token: str = ""
    hh_user_agent: str = "hh-parser-bot/1.0 (change-me@example.com)"
    # SOCKS5/HTTP-прокси для запросов к hh.ru: парсинг идёт с российского IP,
    # а не с адреса хостинга, где крутится бот. Пусто — напрямую.
    # Пример: socks5://17.9.7.5:1080
    hh_proxy_url: str = ""

    # Хабр Карьера — второй источник вакансий. Ходит через тот же HH_PROXY_URL
    # и с тем же HH_USER_AGENT, что и hh.ru.
    habr_enabled: bool = True

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # SOCKS5/HTTP-прокси для доступа к Telegram API (нужен там, где Telegram заблокирован).
    # Пример: socks5://warp:1080
    telegram_proxy_url: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://hh:hh@db:5432/hh_pars"

    # Parser
    parse_interval_minutes: int = 30
    hh_search_text: str = "python developer"
    hh_search_area: str = "1"

    log_level: str = "INFO"

    # Отклики по кнопке «Подтвердить» под вакансией — только для владельца бота,
    # от его аккаунтов hh.ru и Хабр Карьеры (cookies сессии из браузера).
    # 0 — отклики выключены, кнопок нет.
    owner_telegram_id: int = 0
    # Ключ Fernet для cookies в БД. Сгенерировать:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Сменился ключ — сохранённые входы не расшифровать, подключать заново.
    session_encryption_key: str = ""
    # User-Agent запросов от имени владельца: как у обычного браузера, а не бота.
    browser_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    def is_owner(self, user_id: int) -> bool:
        return bool(self.owner_telegram_id) and user_id == self.owner_telegram_id


settings = Settings()
