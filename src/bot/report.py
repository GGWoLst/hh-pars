from datetime import UTC, datetime, timedelta
from io import BytesIO

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from openpyxl import Workbook
from sqlalchemy import select

from src.bot.keyboards import MAIN_MENU_REPORT, PERIODS, period_kb, preset_label
from src.storage.db import get_session
from src.storage.models import FoundVacancy, SearchPreset

router = Router()

_PERIOD_DELTAS = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}


@router.message(lambda m: m.text == MAIN_MENU_REPORT)
async def ask_report_period(message: Message) -> None:
    await message.answer("За какой период выгрузить вакансии?", reply_markup=period_kb())


@router.callback_query(F.data.startswith("period:"))
async def send_report(callback: CallbackQuery) -> None:
    period = callback.data.removeprefix("period:")
    delta = _PERIOD_DELTAS.get(period)
    if delta is None:
        await callback.answer("Неизвестный период.", show_alert=True)
        return

    since = datetime.now(UTC) - delta

    async with get_session() as session:
        rows = (
            await session.execute(
                select(FoundVacancy, SearchPreset)
                .join(SearchPreset, FoundVacancy.preset_id == SearchPreset.id)
                .where(
                    SearchPreset.user_id == callback.from_user.id,
                    FoundVacancy.found_at >= since,
                )
                .order_by(FoundVacancy.found_at.desc())
            )
        ).all()

    await callback.message.edit_reply_markup(reply_markup=None)

    if not rows:
        await callback.message.answer(f"За «{PERIODS[period]}» вакансий не найдено.")
        await callback.answer()
        return

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Вакансии"
    sheet.append(["Найдено", "Пресет", "Вакансия", "Компания", "Ссылка"])

    for vacancy, preset in rows:
        sheet.append(
            [
                vacancy.found_at.strftime("%Y-%m-%d %H:%M"),
                preset_label(preset.profession, preset.stack, preset.experience, preset.area),
                vacancy.name,
                vacancy.employer or "—",
                vacancy.url,
            ]
        )

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    filename = f"vacancies_{period}_{datetime.now(UTC):%Y%m%d}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(buffer.read(), filename=filename),
        caption=f"«{PERIODS[period]}»: {len(rows)} вакансий",
    )
    await callback.answer()
