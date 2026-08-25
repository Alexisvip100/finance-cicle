import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class AccountType(str, enum.Enum):
    CASH = "CASH"
    DEBIT = "DEBIT"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType, native_enum=False), nullable=False)
    # Solo aplica a DEBIT (una cuenta CASH no tiene banco) — se agrega para el
    # flujo de "agregar tarjeta de débito" desde Tarjetas.
    bank: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
