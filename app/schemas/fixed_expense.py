from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator


class FixedExpenseCreate(BaseModel):
    name: str
    amount: Decimal
    day_of_month: int
    category_id: int
    account_id: Optional[int] = None
    credit_card_id: Optional[int] = None
    is_active: bool = True

    @model_validator(mode="after")
    def _validate_exactly_one_source(self):
        has_account = self.account_id is not None
        has_card = self.credit_card_id is not None
        if has_account == has_card:  # ambos o ninguno
            raise ValueError("Debes dar exactamente uno: account_id o credit_card_id")
        return self


class FixedExpenseUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[Decimal] = None
    day_of_month: Optional[int] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    credit_card_id: Optional[int] = None
    is_active: Optional[bool] = None


class FixedExpensePay(BaseModel):
    # Por defecto se registra con fecha de hoy — se puede pasar otra fecha
    # si el usuario está capturando un pago que ya hizo días atrás.
    transaction_date: Optional[date] = None
    account_id: Optional[int] = None
    credit_card_id: Optional[int] = None

    @model_validator(mode="after")
    def _validate_source(self):
        if self.account_id is not None and self.credit_card_id is not None:
            raise ValueError("Solo puedes especificar una fuente: account_id o credit_card_id")
        return self


class FixedExpenseRead(BaseModel):
    id: int
    name: str
    amount: Decimal
    day_of_month: int
    category_id: int
    account_id: Optional[int]
    credit_card_id: Optional[int]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
