from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class IncomeReceipt(Base):
    """Registro de que un ingreso programado (Income) se cobró de verdad en
    una fecha concreta. Income es solo el horario esperado (para proyectar en
    Flujo/Disponible real); esto es el historial real de "ya me pagaron".
    """

    __tablename__ = "income_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    income_id: Mapped[int] = mapped_column(ForeignKey("incomes.id"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
