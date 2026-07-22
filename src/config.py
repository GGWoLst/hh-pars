from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # HH.ru API
    hh_client_id: str = ""
    hh_client_secret: str = ""
    hh_access_token: str = ""
    hh_user_agent: str = "hh-parser-bot/1.0 (change-me@example.com)"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://hh:hh@db:5432/hh_pars"

    # Parser
    parse_interval_minutes: int = 30
    hh_search_text: str = "python developer"
    hh_search_area: str = "1"

    log_level: str = "INFO"


settings = Settings()
