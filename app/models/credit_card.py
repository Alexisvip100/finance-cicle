from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class CreditCard(Base):
    __tablename__ = "credit_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank: Mapped[str] = mapped_column(String(120), nullable=False)
    last_four: Mapped[str] = mapped_column(String(4), nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    # Día de corte declarado (1-31). El día real usado se resuelve en runtime
    # (cycle_service) porque no todos los meses tienen ese día.
    statement_day: Mapped[int] = mapped_column(nullable=False)
    payment_term_days: Mapped[int] = mapped_column(nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
