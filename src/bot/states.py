from aiogram.fsm.state import State, StatesGroup


class PresetForm(StatesGroup):
    profession = State()
    stack = State()
    grade = State()
    area = State()


class ApplyForm(StatesGroup):
    cookies = State()  # ждём cookies площадки (в data — source)
    letter = State()  # ждём шаблон сопроводительного письма
