"""budget_service: gasto por categoría en un mes natural (§7, §8.8).

Todo devengado (regla 4.5: una compra a MSI cuenta completa en el mes de la
compra, nunca prorrateada) — por eso basta sumar Transaction.amount por mes,
sin tocar billing_cycles para el total. Lo que SÍ mira los ciclos es el
desglose de "cuánto de lo gastado con tarjeta sigue pendiente de salir":
para una compra normal, pendiente hasta que su ciclo quede PAID; para una
compra a MSI, pendiente = mensualidades que aún no se han pagado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.category import Category
from app.models.income import Income
from app.models.installment_plan import InstallmentPlan
from app.models.transaction import PaymentMethod, Transaction

ZERO = Decimal("0")


@dataclass(frozen=True)
class CategoryBudgetSummary:
    # None = gastos sin categoría ("Sin categoría" — la categoría ya no es
    # obligatoria al registrar un gasto).
    category_id: Optional[int]
    category_name: str
    monthly_limit: Optional[Decimal]
    spent: Decimal
    credit_spent: Decimal
    credit_pending: Decimal
    created_at: Optional[datetime]


def _month_bounds(month: str):
    year, month_num = (int(part) for part in month.split("-"))
    return year, month_num


def month_summary(session: Session, user_id: int, month: str) -> List[CategoryBudgetSummary]:
    year, month_num = _month_bounds(month)

    stmt = select(Transaction).where(Transaction.user_id == user_id)
    transactions = [
        t for t in session.execute(stmt).scalars()
        if t.transaction_date.year == year and t.transaction_date.month == month_num
    ]

    by_category: Dict[Optional[int], List[Transaction]] = {}
    for t in transactions:
        by_category.setdefault(t.category_id, []).append(t)

    categories_stmt = select(Category).where(Category.user_id == user_id)
    categories = {c.id: c for c in session.execute(categories_stmt).scalars()}

    def _summarize(
        category_id: Optional[int], name: str, monthly_limit: Optional[Decimal], created_at: Optional[datetime]
    ) -> Optional[CategoryBudgetSummary]:
        txns = by_category.get(category_id, [])
        spent = sum((t.amount for t in txns), start=ZERO)
        if spent == ZERO and monthly_limit is None:
            return None  # nada que reportar para este mes
        credit_txns = [t for t in txns if t.payment_method == PaymentMethod.CREDIT]
        credit_spent = sum((t.amount for t in credit_txns), start=ZERO)
        credit_pending = sum((_pending_amount(session, t) for t in credit_txns), start=ZERO)
        return CategoryBudgetSummary(
            category_id=category_id,
            category_name=name,
            monthly_limit=monthly_limit,
            spent=spent,
            credit_spent=credit_spent,
            credit_pending=credit_pending,
            created_at=created_at,
        )

    results: List[CategoryBudgetSummary] = []
    for category_id, category in categories.items():
        summary = _summarize(category_id, category.name, category.monthly_limit, category.created_at)
        if summary is not None:
            results.append(summary)

    uncategorized = _summarize(None, "Sin categoría", None, None)
    if uncategorized is not None:
        results.append(uncategorized)

    return results


def monthly_income_total(session: Session, user_id: int) -> Decimal:
    """Suma de ingresos activos esperados en CUALQUIER mes calendario.

    `payment_days` ya describe "qué días de cada mes" ocurre el ingreso (ej.
    [15, LAST_DAY] = dos veces todos los meses), así que el total mensual es
    el mismo mes a mes — no depende de a qué mes se le pregunte, por eso no
    recibe `month` (a diferencia de month_summary): un ingreso VARIABLE tiene
    payment_days=[] y por lo tanto no aporta nada aquí (no es proyectable).
    """
    stmt = select(Income).where(Income.user_id == user_id, Income.is_active.is_(True))
    return sum(
        (income.amount * len(income.payment_days) for income in session.execute(stmt).scalars()),
        start=ZERO,
    )


def _pending_amount(session: Session, transaction: Transaction) -> Decimal:
    plan_stmt = select(InstallmentPlan).where(InstallmentPlan.transaction_id == transaction.id)
    plan = session.execute(plan_stmt).scalar_one_or_none()
    if plan is not None:
        remaining_months = plan.months_total - plan.months_paid
        return plan.monthly_amount * remaining_months

    if transaction.billing_cycle_id is None:
        return ZERO
    cycle = session.get(BillingCycle, transaction.billing_cycle_id)
    if cycle is None or cycle.status == CycleStatus.PAID:
        return ZERO
    # La transacción sigue pendiente en proporción a lo que falta pagar del
    # ciclo completo (si el ciclo tiene más de una compra, un pago parcial se
    # reparte proporcionalmente entre todas).
    if cycle.total_amount == ZERO:
        return ZERO
    unpaid_fraction = (cycle.total_amount - cycle.paid_amount) / cycle.total_amount
    return (transaction.amount * unpaid_fraction).quantize(Decimal("0.01"))
