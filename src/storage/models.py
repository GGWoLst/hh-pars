from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram user id
    chat_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    presets: Mapped[list["SearchPreset"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class SearchPreset(Base):
    """Пресет мониторинга: профессия + стек + грейд + регион.

    Коды (profession/stack/experience/area) — ключи словарей в src/bot/keyboards.py,
    человекочитаемые подписи вычисляются оттуда, а не хранятся здесь.
    """

    __tablename__ = "search_presets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    profession: Mapped[str] = mapped_column(String)
    stack: Mapped[str] = mapped_column(String)  # код стека или "any"
    experience: Mapped[str | None] = mapped_column(String, nullable=True)  # None = любой опыт
    area: Mapped[str] = mapped_column(String, default="113")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="presets")
    found_vacancies: Mapped[list["FoundVacancy"]] = relationship(
        back_populates="preset", cascade="all, delete-orphan"
    )


class FoundVacancy(Base):
    """Вакансия, найденная по пресету — используется и для дедупа рассылки,
    и как источник данных для Excel-отчётов."""

    __tablename__ = "found_vacancies"

    id: Mapped[int] = mapped_column(primary_key=True)
    preset_id: Mapped[int] = mapped_column(ForeignKey("search_presets.id"))
    vacancy_id: Mapped[str] = mapped_column(String)  # id вакансии на hh.ru
    name: Mapped[str] = mapped_column(String)
    employer: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    preset: Mapped["SearchPreset"] = relationship(back_populates="found_vacancies")
