from decimal import Decimal
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.income import DAY_ADJUSTED_PATTERN, LAST_DAY, WEEK_WEEKDAY_PATTERN, IncomeFrequency

PaymentDay = Union[int, str]


def _validate_payment_days(value: List[PaymentDay]) -> List[PaymentDay]:
    for day in value:
        if isinstance(day, str):
            if day != LAST_DAY and not WEEK_WEEKDAY_PATTERN.match(day) and not DAY_ADJUSTED_PATTERN.match(day):
                raise ValueError(
                    f"Valor de día inválido: {day!r} (se acepta '{LAST_DAY}', semana de pago 'W1-FRI'..'WLAST-FRI', o día ajustado 'D15-ADJ')"
                )
        elif not (1 <= day <= 31):
            raise ValueError(f"Día de pago fuera de rango: {day}")
    return value


class IncomeCreate(BaseModel):
    name: str
    amount: Decimal
    frequency: IncomeFrequency
    payment_days: List[PaymentDay] = []
    account_id: int
    is_active: bool = True

    @field_validator("payment_days")
    @classmethod
    def validate_payment_days(cls, value):
        return _validate_payment_days(value)


class IncomeUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[Decimal] = None
    frequency: Optional[IncomeFrequency] = None
    payment_days: Optional[List[PaymentDay]] = None
    is_active: Optional[bool] = None

    @field_validator("payment_days")
    @classmethod
    def validate_payment_days(cls, value):
        if value is None:
            return value
        return _validate_payment_days(value)


class IncomeRead(BaseModel):
    id: int
    name: str
    amount: Decimal
    frequency: IncomeFrequency
    payment_days: List[PaymentDay]
    account_id: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
