from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.account import AccountType


class AccountCreate(BaseModel):
    name: str
    type: AccountType
    bank: Optional[str] = None
    balance: Decimal = Decimal("0")
    color: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    bank: Optional[str] = None
    balance: Optional[Decimal] = None
    color: Optional[str] = None


class AccountRead(BaseModel):
    id: int
    name: str
    type: AccountType
    bank: Optional[str]
    balance: Decimal
    color: Optional[str]

    model_config = ConfigDict(from_attributes=True)
