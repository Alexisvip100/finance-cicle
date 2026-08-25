from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class IncomeReceiptCreate(BaseModel):
    # Por defecto hoy y el monto configurado del ingreso — ambos opcionales
    # por si un mes te pagaron en otra fecha o un monto distinto (ej. bono).
    received_date: Optional[date] = None
    amount: Optional[Decimal] = None


class IncomeReceiptRead(BaseModel):
    id: int
    income_id: int
    account_id: int
    amount: Decimal
    received_date: date

    model_config = ConfigDict(from_attributes=True)
