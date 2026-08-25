from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FixedExpense(Base):
    """Gasto recurrente en fecha conocida (renta, suscripciones). Se paga desde
    una cuenta o desde una tarjeta de crédito, nunca ambas — ver constraint en DB
    de aplicación (services), SQLite/PG no validan XOR entre columnas nulas de forma nativa.
    """

    __tablename__ = "fixed_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    day_of_month: Mapped[int] = mapped_column(nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    credit_card_id: Mapped[Optional[int]] = mapped_column(ForeignKey("credit_cards.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
