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

# Хабр Карьера фильтрует по своим id, а не по тексту: её q= полнотекстовый и шумный.
# Справочники — блок data-ssr-state на career.habr.com/vacancies.
# s[] — специализации, объединяются по ИЛИ.
HABR_SPECIALIZATIONS = {
    "backend": (2,),
    "frontend": (3,),
    "fullstack": (4,),
    "mobile": (5,),
    "data": (44, 125),  # Data Scientist, ML-разработчик
    "devops": (22,),
    "qa": (12, 10),  # тестировщик, автоматизация тестирования
    "analyst": (43,),  # аналитик данных
    "sysadmin": (17, 18),  # системный администратор, администратор серверов
    "pm": (32, 34),  # менеджер проекта, менеджер продукта
}

# skills[] объединяются по И, поэтому несколько навыков — отдельные запросы.
HABR_SKILLS = {
    "python": (446,),
    "java": (1012,),
    "go": (101,),
    "js": (264, 245),  # JavaScript, TypeScript
    "csharp": (706,),
    "php": (1005,),
    "cpp": (172,),
    "sql": (322,),
    "onec": (669,),  # разработка под 1С
}

# qid[] — грейд, по ИЛИ: Intern 1, Junior 3, Middle 4, Senior 5, Lead 6.
# Стажа, как на hh.ru, у Хабра нет — переводим примерно. Вакансии без грейда
# (~15%) фильтр отбрасывает, поэтому при «Любом опыте» его не задаём.
HABR_GRADES = {
    "noExperience": (1, 3),
    "between1And3": (3, 4),
    "between3And6": (4, 5),
    "moreThan6": (5, 6),
}

# Фильтра «вся Россия» у Хабра нет — для неё город не задаём.
HABR_CITIES = {
    "1": 678,
    "2": 679,
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
MAIN_MENU_APPLY = "⚙️ Отклики"  # только у владельца бота

MAIN_MENU_LABELS = {
    MAIN_MENU_NEW_PRESET,
    MAIN_MENU_MY_PRESETS,
    MAIN_MENU_CHECK_NOW,
    MAIN_MENU_REPORT,
    MAIN_MENU_APPLY,
}


def main_menu_kb(owner: bool = False) -> ReplyKeyboardMarkup:
    last_row = [KeyboardButton(text=MAIN_MENU_REPORT)]
    if owner:
        last_row.append(KeyboardButton(text=MAIN_MENU_APPLY))
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MAIN_MENU_NEW_PRESET)],
            [KeyboardButton(text=MAIN_MENU_MY_PRESETS), KeyboardButton(text=MAIN_MENU_CHECK_NOW)],
            last_row,
        ],
        resize_keyboard=True,
    )


def decision_kb(found_vacancy_id: int) -> InlineKeyboardMarkup:
    """Кнопки под вакансией у владельца: откликнуться или убрать."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data=f"apply:{found_vacancy_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"reject:{found_vacancy_id}"
                ),
            ]
        ]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="acc:cancel")]]
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


def habr_query_params(
    profession: str, stack: str, experience: str | None, area: str
) -> list[list[tuple[str, int]]]:
    """Фильтры запроса к Хабр Карьере по пресету — по набору на каждый навык стека.

    Пустой список — профессии нет в справочнике Хабра, площадку для пресета пропускаем.
    """
    specializations = HABR_SPECIALIZATIONS.get(profession)
    if not specializations:
        return []

    base = [("s[]", spec) for spec in specializations]
    base += [("qid[]", grade) for grade in HABR_GRADES.get(experience or "any", ())]
    if area in HABR_CITIES:
        base.append(("city_id", HABR_CITIES[area]))

    skills = HABR_SKILLS.get(stack)
    if not skills:
        return [base]
    return [[*base, ("skills[]", skill)] for skill in skills]
