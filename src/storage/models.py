from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    # id на площадке: у hh.ru — число, у Хабр Карьеры — "habr:<id>" (см. src/sources.py)
    vacancy_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    employer: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    preset: Mapped["SearchPreset"] = relationship(back_populates="found_vacancies")
    decision: Mapped["VacancyDecision | None"] = relationship(
        back_populates="vacancy", cascade="all, delete-orphan", uselist=False
    )


class VacancyDecision(Base):
    """Что владелец сделал с вакансией по кнопкам под ней.

    Отдельная таблица, а не колонка в found_vacancies: init_models делает только
    create_all, а он не добавляет колонки в существующие таблицы.
    """

    __tablename__ = "vacancy_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    found_vacancy_id: Mapped[int] = mapped_column(ForeignKey("found_vacancies.id"), unique=True)
    status: Mapped[str] = mapped_column(String)  # applied | rejected | manual
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vacancy: Mapped["FoundVacancy"] = relationship(back_populates="decision")


class AccountSession(Base):
    """Вход владельца на площадку для откликов: cookies браузерной сессии, зашифрованные."""

    __tablename__ = "account_sessions"
    __table_args__ = (UniqueConstraint("user_id", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String)  # hh | habr
    cookies: Mapped[str] = mapped_column(Text)  # Fernet(JSON {имя: значение})
    account_name: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_id: Mapped[str | None] = mapped_column(String, nullable=True)  # hash резюме hh.ru
    resume_title: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplySettings(Base):
    __tablename__ = "apply_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    # Шаблон сопроводительного письма; {вакансия} и {компания} подставляются.
    letter_template: Mapped[str] = mapped_column(Text, default="")
