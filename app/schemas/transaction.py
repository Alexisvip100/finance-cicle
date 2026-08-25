from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.transaction import PaymentMethod


class TransactionCreate(BaseModel):
    amount: Decimal
    category_id: Optional[int] = None
    # Obligatorio: reemplaza a la categoría como el único dato requerido
    # sobre "qué fue" el gasto.
    description: str = Field(min_length=1)
    transaction_date: date
    payment_method: PaymentMethod
    account_id: Optional[int] = None
    credit_card_id: Optional[int] = None
    # Si se da, la compra se registra a MSI: el monto completo se devenga en
    # `transaction_date` (regla 4.5) y flow_service proyecta las mensualidades.
    installment_months: Optional[int] = None

    @model_validator(mode="after")
    def _validate_payment_source(self):
        if self.payment_method == PaymentMethod.CREDIT:
            if not self.credit_card_id or self.account_id:
                raise ValueError("Un gasto CREDIT debe traer credit_card_id y no account_id")
        else:
            if not self.account_id or self.credit_card_id:
                raise ValueError("Un gasto CASH/DEBIT debe traer account_id y no credit_card_id")
            if self.installment_months:
                raise ValueError("Solo las compras CREDIT pueden ser a MSI")
        return self


class TransactionRead(BaseModel):
    id: int
    amount: Decimal
    category_id: Optional[int]
    description: Optional[str]
    transaction_date: date
    cash_flow_date: date
    payment_method: PaymentMethod
    account_id: Optional[int]
    credit_card_id: Optional[int]
    billing_cycle_id: Optional[int]
    fixed_expense_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)
