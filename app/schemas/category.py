from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CategoryCreate(BaseModel):
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    monthly_limit: Optional[Decimal] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    monthly_limit: Optional[Decimal] = None


class CategoryRead(BaseModel):
    id: int
    name: str
    icon: Optional[str]
    color: Optional[str]
    monthly_limit: Optional[Decimal]

    model_config = ConfigDict(from_attributes=True)
