from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class SavingsAllocation(Base):
    """Dinero que el usuario reservó voluntariamente para pagar un ciclo cerrado
    específico. Vive dentro del saldo de la cuenta origen (no se mueve dinero de
    verdad) — es solo un marcador de intención usado para sugerir aportaciones
    y como origen alterno al registrar un pago (ver Payment.source).
    """

    __tablename__ = "savings_allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_card_id: Mapped[int] = mapped_column(ForeignKey("credit_cards.id"), index=True, nullable=False)
    billing_cycle_id: Mapped[int] = mapped_column(ForeignKey("billing_cycles.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
