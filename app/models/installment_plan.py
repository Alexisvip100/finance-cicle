from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InstallmentPlan(Base):
    """Meses sin intereses (MSI). Una sola fila representa las N obligaciones:
    flow_service proyecta virtualmente `monthly_amount` en cada ciclo futuro hasta
    `months_total`, sin crear una Transaction por cada mensualidad (eso duplicaría
    el gasto devengado, que ya se contó completo en la transacción original).
    """

    __tablename__ = "installment_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_card_id: Mapped[int] = mapped_column(ForeignKey("credit_cards.id"), index=True, nullable=False)
    # Transacción original (la compra completa, devengada en start_date).
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), unique=True, nullable=False
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    months_total: Mapped[int] = mapped_column(nullable=False)
    months_paid: Mapped[int] = mapped_column(default=0)
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
