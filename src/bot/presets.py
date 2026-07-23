from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.bot.keyboards import (
    MAIN_MENU_MY_PRESETS,
    MAIN_MENU_NEW_PRESET,
    area_kb,
    delete_preset_kb,
    grade_kb,
    main_menu_kb,
    preset_label,
    profession_kb,
    stack_kb,
)
from src.bot.states import PresetForm
from src.storage.db import get_session
from src.storage.models import SearchPreset

router = Router()


@router.message(lambda m: m.text == MAIN_MENU_NEW_PRESET)
async def start_new_preset(message: Message, state: FSMContext) -> None:
    await state.set_state(PresetForm.profession)
    await message.answer("Кого ищем?", reply_markup=profession_kb())


@router.callback_query(PresetForm.profession, F.data.startswith("prof:"))
async def profession_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(profession=callback.data.removeprefix("prof:"))
    await state.set_state(PresetForm.stack)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Какой стек?", reply_markup=stack_kb())
    await callback.answer()


@router.callback_query(PresetForm.stack, F.data.startswith("stack:"))
async def stack_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(stack=callback.data.removeprefix("stack:"))
    await state.set_state(PresetForm.grade)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Какой грейд?", reply_markup=grade_kb())
    await callback.answer()


@router.callback_query(PresetForm.grade, F.data.startswith("grade:"))
async def grade_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.removeprefix("grade:")
    await state.update_data(grade=None if code == "any" else code)
    await state.set_state(PresetForm.area)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Какой регион?", reply_markup=area_kb())
    await callback.answer()


@router.callback_query(PresetForm.area, F.data.startswith("area:"))
async def area_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.update_data(area=callback.data.removeprefix("area:"))
    await state.clear()

    async with get_session() as session:
        preset = SearchPreset(
            user_id=callback.from_user.id,
            profession=data["profession"],
            stack=data["stack"],
            experience=data["grade"],
            area=data["area"],
        )
        session.add(preset)
        await session.commit()
        label = preset_label(preset.profession, preset.stack, preset.experience, preset.area)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Готово! Поставил на мониторинг:\n{label}",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.message(lambda m: m.text == MAIN_MENU_MY_PRESETS)
async def list_presets(message: Message) -> None:
    async with get_session() as session:
        presets = (
            await session.scalars(
                select(SearchPreset).where(SearchPreset.user_id == message.from_user.id)
            )
        ).all()
        labels = [
            (p.id, preset_label(p.profession, p.stack, p.experience, p.area)) for p in presets
        ]

    if not labels:
        await message.answer("Пресетов пока нет — добавь через «➕ Новый пресет».")
        return

    for preset_id, label in labels:
        await message.answer(label, reply_markup=delete_preset_kb(preset_id))


@router.callback_query(F.data.startswith("del:"))
async def delete_preset(callback: CallbackQuery) -> None:
    preset_id = int(callback.data.removeprefix("del:"))

    async with get_session() as session:
        preset = await session.get(SearchPreset, preset_id)
        if preset is None or preset.user_id != callback.from_user.id:
            await callback.answer("Пресет не найден.", show_alert=True)
            return

        await session.delete(preset)
        await session.commit()

    await callback.message.edit_text("Пресет удалён.")
    await callback.answer()
