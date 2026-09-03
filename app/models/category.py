from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    monthly_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
