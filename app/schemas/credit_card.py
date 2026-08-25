from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.billing_cycle import CycleStatus


class CreditCardCreate(BaseModel):
    name: str
    bank: str
    last_four: str
    credit_limit: Decimal = Decimal("0")
    statement_day: int
    payment_term_days: int
    color: Optional[str] = None
    # Caso de prueba #8: tarjeta agregada con deuda preexistente — captura un
    # ciclo cerrado inicial en vez de asumir que la tarjeta empieza en $0.
    initial_balance: Optional[Decimal] = None
    initial_due_date: Optional[date] = None


class CreditCardUpdate(BaseModel):
    name: Optional[str] = None
    bank: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    statement_day: Optional[int] = None
    payment_term_days: Optional[int] = None
    color: Optional[str] = None


class CreditCardRead(BaseModel):
    id: int
    name: str
    bank: str
    last_four: str
    credit_limit: Decimal
    statement_day: int
    payment_term_days: int
    color: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class BillingCycleRead(BaseModel):
    id: int
    start_date: date
    end_date: date
    due_date: date
    status: CycleStatus
    total_amount: Decimal
    paid_amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class InstallmentPlanRead(BaseModel):
    id: int
    description: str
    total_amount: Decimal
    months_total: int
    months_paid: int
    monthly_amount: Decimal
    start_date: date

    model_config = ConfigDict(from_attributes=True)


class CreditCardDetail(CreditCardRead):
    current_cycle: Optional[BillingCycleRead] = None
    # El ciclo cerrado más antiguo que todavía no se paga por completo ("por pagar").
    pending_cycle: Optional[BillingCycleRead] = None
    allocated_for_pending_cycle: Decimal = Decimal("0")
    installment_plans: List[InstallmentPlanRead] = []
    # Ciclo PAID más reciente, solo cuando no hay ningún pending_cycle: es la
    # señal de "ya hice el pago" que se muestra como palomita verde en la app.
    last_paid_cycle: Optional[BillingCycleRead] = None
    # límite - (ciclo actual + ciclos sin pagar + MSI restante). Baja en el
    # momento de la compra, sube cuando pagas — independiente de comprometido.
    available_credit: Decimal = Decimal("0")
