"""balance_service: disponible real (regla 4.2).

    disponible_real = cuentas − comprometido − fijos_pendientes

- comprometido: ciclos CLOSED o PARTIALLY_PAID (deuda exigible), su saldo
  restante (total_amount - paid_amount). Los OPEN no cuentan (no son deuda
  exigible todavía) y los PAID tampoco (ya no se debe nada).
- fijos_pendientes: fixed_expenses activos cuyo día de cobro cae en
  [as_of, próximo ingreso) — todavía no se han cobrado en el periodo actual.
- el apartado (SavingsAllocation) NUNCA se resta aquí: ya está contenido
  dentro del saldo de las cuentas y dentro de "comprometido". Restarlo sería
  doble conteo (regla 4.2, explícita).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dates import add_months, resolve_day_of_month
from app.models.account import Account
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.credit_card import CreditCard
from app.models.fixed_expense import FixedExpense
from app.models.income import Income
from app.services.income_schedule import next_income_date

ZERO = Decimal("0")

# Ciclos con deuda exigible: ya cerraron, ya tienen monto fijo. OPEN se excluye
# a propósito (no es deuda exigible) y PAID se excluye porque ya no se debe nada.
COMMITTED_STATUSES = (CycleStatus.CLOSED, CycleStatus.PARTIALLY_PAID)


@dataclass(frozen=True)
class AvailableBreakdown:
    accounts_total: Decimal
    committed: Decimal
    pending_fixed: Decimal
    next_income_date: Optional[date]
    available: Decimal


def calculate_accounts_total(session: Session, user_id: int) -> Decimal:
    stmt = select(Account.balance).where(Account.user_id == user_id)
    return sum(session.execute(stmt).scalars(), start=ZERO)


def calculate_committed(session: Session, user_id: int) -> Decimal:
    stmt = (
        select(BillingCycle)
        .join(CreditCard, BillingCycle.credit_card_id == CreditCard.id)
        .where(CreditCard.user_id == user_id, BillingCycle.status.in_(COMMITTED_STATUSES))
    )
    cycles = session.execute(stmt).scalars()
    return sum((c.total_amount - c.paid_amount for c in cycles), start=ZERO)


def _occurrences_in_range(day_or_last, range_start: date, range_end: date) -> List[date]:
    """Resuelve `day_or_last` en cada mes tocado por [range_start, range_end)
    y regresa las ocurrencias que de verdad caen dentro del rango. Casi
    siempre serán 0 o 1, pero un rango que cruza fin de mes puede dar más.
    """
    occurrences: List[date] = []
    year, month = range_start.year, range_start.month
    while date(year, month, 1) <= range_end:
        candidate = resolve_day_of_month(year, month, day_or_last)
        if range_start <= candidate < range_end:
            occurrences.append(candidate)
        year, month = add_months(year, month, 1)
    return occurrences


def calculate_pending_fixed(
    session: Session, user_id: int, as_of: date, until: Optional[date]
) -> Decimal:
    """`until` es la fecha del próximo ingreso. Si no hay ningún ingreso
    resoluble (todos VARIABLE o no hay ninguno configurado), no hay un límite
    de periodo definido por la regla 4.2 — se regresa 0 explícitamente en vez
    de adivinar una ventana arbitraria.
    """
    if until is None:
        return ZERO

    stmt = select(FixedExpense).where(FixedExpense.user_id == user_id, FixedExpense.is_active.is_(True))
    total = ZERO
    for fixed in session.execute(stmt).scalars():
        occurrences = _occurrences_in_range(fixed.day_of_month, as_of, until)
        total += fixed.amount * len(occurrences)
    return total


def calculate_available(session: Session, user_id: int, as_of: Optional[date] = None) -> AvailableBreakdown:
    as_of = as_of or date.today()

    accounts_total = calculate_accounts_total(session, user_id)
    committed = calculate_committed(session, user_id)

    incomes_stmt = select(Income).where(Income.user_id == user_id, Income.is_active.is_(True))
    active_incomes = list(session.execute(incomes_stmt).scalars())
    upcoming_income = next_income_date(active_incomes, as_of)

    pending_fixed = calculate_pending_fixed(session, user_id, as_of, upcoming_income)

    available = accounts_total - committed - pending_fixed
    return AvailableBreakdown(
        accounts_total=accounts_total,
        committed=committed,
        pending_fixed=pending_fixed,
        next_income_date=upcoming_income,
        available=available,
    )
