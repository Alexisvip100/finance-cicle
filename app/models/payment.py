import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class PaymentSource(str, enum.Enum):
    ACCOUNT = "ACCOUNT"
    ALLOCATION = "ALLOCATION"


class Payment(Base):
    """Pago aplicado siempre contra un billing_cycle específico (nunca contra
    "la tarjeta" en abstracto). `source` indica si el dinero salió de una cuenta
    o del apartado de esa tarjeta/ciclo.

    Nota de esquema: la spec original describe `source` como una sola columna
    que vale "account_id | 'ALLOCATION'" (mezclando una FK con un literal). Eso
    rompe la integridad referencial, así que aquí se separa en `source_type`
    (enum) + `source_account_id` (FK, solo se llena cuando source_type=ACCOUNT).
    Marcado para tu revisión explícita.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    billing_cycle_id: Mapped[int] = mapped_column(ForeignKey("billing_cycles.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[PaymentSource] = mapped_column(Enum(PaymentSource, native_enum=False), nullable=False)
    source_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
