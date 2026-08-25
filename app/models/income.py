import enum
import re
from decimal import Decimal
from typing import List, Optional, Union

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.dates import WEEKDAY_CODES

# Sentinel usado dentro de `payment_days` en vez del número 30/31, que no existe
# en todos los meses. Se resuelve en runtime a "el último día real del mes".
LAST_DAY = "LAST_DAY"

# Alternativa a un día fijo del mes: "semana de pago" (ej. "el último viernes",
# no un número de día — paydays que se recorren de semana en semana, no de
# día en día). Formato "W{1-4|LAST}-{MON..SUN}", ej. "W3-FRI", "WLAST-FRI".
WEEK_WEEKDAY_PATTERN = re.compile(r"^W(1|2|3|4|LAST)-(" + "|".join(WEEKDAY_CODES) + r")$")

# Día fijo del mes, pero recorrido al viernes anterior si cae sábado/domingo
# (nómina típica: "el 15, o el viernes antes si el 15 cae en fin de semana").
# Formato "D{día 1-31}-ADJ", ej. "D15-ADJ".
DAY_ADJUSTED_PATTERN = re.compile(r"^D([1-9]|[12][0-9]|3[01])-ADJ$")

PaymentDay = Union[int, str]  # int (1-31), LAST_DAY, "W{semana}-{día}", o "D{día}-ADJ"


def parse_week_weekday(value: str) -> Optional[tuple]:
    """Si `value` tiene el formato de semana de pago, regresa (semana, día_código);
    si no, None (es un LAST_DAY, D{día}-ADJ, o no aplica)."""
    match = WEEK_WEEKDAY_PATTERN.match(value)
    if match is None:
        return None
    return match.group(1), match.group(2)


def parse_day_adjusted(value: str) -> Optional[int]:
    """Si `value` tiene el formato de día ajustado (D{día}-ADJ), regresa el
    día como int; si no, None."""
    match = DAY_ADJUSTED_PATTERN.match(value)
    if match is None:
        return None
    return int(match.group(1))


class IncomeFrequency(str, enum.Enum):
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"
    VARIABLE = "VARIABLE"


class Income(Base):
    __tablename__ = "incomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    frequency: Mapped[IncomeFrequency] = mapped_column(Enum(IncomeFrequency, native_enum=False), nullable=False)
    payment_days: Mapped[List[PaymentDay]] = mapped_column(JSON, default=list)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
