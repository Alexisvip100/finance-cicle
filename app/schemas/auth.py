from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    currency: str = "MXN"
    timezone: str = "America/Mexico_City"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: int
    email: EmailStr
    currency: str
    timezone: str
    monthly_spending_goal: Optional[Decimal]

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    monthly_spending_goal: Optional[Decimal] = None
