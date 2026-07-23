from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# code -> подпись
PROFESSIONS = {
    "backend": "Backend-разработчик",
    "frontend": "Frontend-разработчик",
    "fullstack": "Fullstack-разработчик",
    "mobile": "Mobile-разработчик",
    "data": "Data Science / ML",
    "devops": "DevOps-инженер",
    "qa": "QA-инженер",
    "analyst": "Аналитик",
    "sysadmin": "Системный администратор",
    "pm": "Project/Product менеджер",
}

# code -> поисковая фраза для hh.ru
PROFESSION_QUERY = {
    "backend": "backend разработчик",
    "frontend": "frontend разработчик",
    "fullstack": "fullstack разработчик",
    "mobile": "mobile разработчик",
    "data": "data scientist",
    "devops": "devops инженер",
    "qa": "тестировщик QA",
    "analyst": "аналитик данных",
    "sysadmin": "системный администратор",
    "pm": "project manager IT",
}

STACKS = {
    "python": "Python",
    "java": "Java",
    "js": "JavaScript/TypeScript",
    "go": "Go",
    "csharp": "C#/.NET",
    "php": "PHP",
    "cpp": "C++",
    "sql": "SQL/DBA",
    "onec": "1C",
    "any": "Без привязки к стеку",
}

GRADES = {
    "noExperience": "Без опыта",
    "between1And3": "1–3 года",
    "between3And6": "3–6 лет",
    "moreThan6": "Более 6 лет",
    "any": "Любой опыт",
}

AREAS = {
    "1": "Москва",
    "2": "Санкт-Петербург",
    "113": "Вся Россия",
}

PERIODS = {
    "day": "За день",
    "week": "За неделю",
    "month": "За месяц",
}

MAIN_MENU_NEW_PRESET = "➕ Новый пресет"
MAIN_MENU_MY_PRESETS = "📋 Мои пресеты"
MAIN_MENU_CHECK_NOW = "🔍 Проверить сейчас"
MAIN_MENU_REPORT = "📊 Отчёт Excel"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MAIN_MENU_NEW_PRESET)],
            [KeyboardButton(text=MAIN_MENU_MY_PRESETS), KeyboardButton(text=MAIN_MENU_CHECK_NOW)],
            [KeyboardButton(text=MAIN_MENU_REPORT)],
        ],
        resize_keyboard=True,
    )


def _paired_inline_kb(options: dict[str, str], callback_prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"{callback_prefix}:{code}")
        for code, label in options.items()
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profession_kb() -> InlineKeyboardMarkup:
    return _paired_inline_kb(PROFESSIONS, "prof")


def stack_kb() -> InlineKeyboardMarkup:
    return _paired_inline_kb(STACKS, "stack")


def grade_kb() -> InlineKeyboardMarkup:
    return _paired_inline_kb(GRADES, "grade")


def area_kb() -> InlineKeyboardMarkup:
    return _paired_inline_kb(AREAS, "area")


def period_kb() -> InlineKeyboardMarkup:
    return _paired_inline_kb(PERIODS, "period")


def delete_preset_kb(preset_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{preset_id}")]]
    )


def preset_label(profession: str, stack: str, experience: str | None, area: str) -> str:
    parts = [
        PROFESSIONS.get(profession, profession),
        STACKS.get(stack, stack),
        GRADES.get(experience or "any", "Любой опыт"),
        AREAS.get(area, area),
    ]
    return " · ".join(parts)


def preset_query_text(profession: str, stack: str) -> str:
    query = PROFESSION_QUERY.get(profession, profession)
    if stack != "any":
        query = f"{query} {STACKS.get(stack, stack)}"
    return query
