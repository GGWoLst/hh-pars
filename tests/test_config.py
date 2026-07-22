from src.config import settings


def test_settings_load() -> None:
    assert settings.hh_user_agent
    assert settings.parse_interval_minutes > 0
