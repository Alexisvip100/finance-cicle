import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CycleStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"


class BillingCycle(Base):
    """Un periodo de facturación de una tarjeta. Se genera con anticipación
    (cycle_service.generate_cycles) y un job diario los cierra cuando corresponde.
    """

    __tablename__ = "billing_cycles"
    __table_args__ = (
        # Dos ciclos de la misma tarjeta nunca deben solaparse en su fecha de inicio.
        UniqueConstraint("credit_card_id", "start_date", name="uq_billing_cycle_card_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_card_id: Mapped[int] = mapped_column(ForeignKey("credit_cards.id"), index=True, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[CycleStatus] = mapped_column(
        Enum(CycleStatus, native_enum=False), default=CycleStatus.OPEN, nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
