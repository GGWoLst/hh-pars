from aiogram.fsm.state import State, StatesGroup


class PresetForm(StatesGroup):
    profession = State()
    stack = State()
    grade = State()
    area = State()
