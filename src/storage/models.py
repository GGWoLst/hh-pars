from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # hh.ru vacancy id
    name: Mapped[str] = mapped_column(String)
    employer: Mapped[str] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
