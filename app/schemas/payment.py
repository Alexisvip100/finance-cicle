from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.payment import PaymentSource


class PaymentCreate(BaseModel):
    billing_cycle_id: int
    amount: Decimal
    source_type: PaymentSource
    # Requerido si source_type == ACCOUNT. Si source_type == ALLOCATION, el
    # dinero sale de la(s) cuenta(s) que originalmente apartaron para este ciclo.
    source_account_id: Optional[int] = None


class PaymentRead(BaseModel):
    id: int
    billing_cycle_id: int
    amount: Decimal
    payment_date: date
    source_type: PaymentSource
    source_account_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)


class AllocationCreate(BaseModel):
    billing_cycle_id: int
    amount: Decimal
    source_account_id: int


class AllocationRead(BaseModel):
    id: int
    billing_cycle_id: int
    amount: Decimal
    source_account_id: int

    model_config = ConfigDict(from_attributes=True)
