"""Площадки, с которых бот берёт вакансии."""

HH = "hh"
HABR = "habr"

SOURCE_LABELS = {
    HH: "hh.ru",
    HABR: "Хабр Карьера",
}

# id вакансий в found_vacancies общие для всех площадок: у hh.ru это голое число,
# у Хабр Карьеры — с префиксом. Так колонка остаётся уникальной без миграции.
HABR_ID_PREFIX = "habr:"


def source_of(vacancy_id: str) -> str:
    return HABR if vacancy_id.startswith(HABR_ID_PREFIX) else HH
