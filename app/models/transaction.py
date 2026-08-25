import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Opcional a propósito: la categoría ya no es obligatoria al registrar un
    # gasto — lo obligatorio es `description` ("¿qué compraste?").
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), index=True, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Criterio devengado: cuándo ocurrió la compra. Es la fecha que usa el presupuesto.
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod, native_enum=False), nullable=False)

    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    credit_card_id: Mapped[Optional[int]] = mapped_column(ForeignKey("credit_cards.id"), nullable=True)
    # Resuelto por cycle_service al insertar (solo si payment_method == CREDIT).
    billing_cycle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("billing_cycles.id"), nullable=True)
    # Se llena solo cuando esta transacción se creó desde "Marcar como pagado"
    # en un gasto fijo (fixed_expenses.pay) — permite mostrarla distinguida en
    # el historial y filtrar por "solo gastos fijos".
    fixed_expense_id: Mapped[Optional[int]] = mapped_column(ForeignKey("fixed_expenses.id"), nullable=True)

    # Criterio caja: fecha real de salida de dinero. == transaction_date si es
    # CASH/DEBIT; == due_date del billing_cycle resuelto si es CREDIT.
    cash_flow_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Sin columna installment_plan_id aquí a propósito: la relación 1:1 con un
    # plan MSI vive solo en installment_plans.transaction_id (decisión
    # explícita del usuario). Para saber si esta transacción originó un plan,
    # consulta InstallmentPlan.transaction_id == transaction.id.
