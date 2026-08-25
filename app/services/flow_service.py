"""flow_service: proyección de saldo y timeline de flujo (§4.3, §8.6).

Solo entran al timeline movimientos reales de caja:
- ingresos futuros (income_schedule)
- pagos de tarjeta en su fecha de VENCIMIENTO, con el monto ya fijo (ciclos
  CLOSED/PARTIALLY_PAID) — nunca en la fecha de corte (regla 4.3).
- mensualidades de MSI todavía no pagadas, en la fecha de vencimiento del
  ciclo que les corresponde (regla 4.5: el flujo registra solo la mensualidad).
- gastos fijos recurrentes.

Un ciclo todavía OPEN no es un pago real (su monto sigue creciendo): solo
aparece como un hito visual sin monto en su fecha de corte (end_date), tal
cual describe la regla 4.3 ("el corte puede aparecer como marcador visual
delgado, sin monto").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dates import add_months, resolve_day_of_month
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.credit_card import CreditCard
from app.models.fixed_expense import FixedExpense
from app.models.income import Income
from app.models.installment_plan import InstallmentPlan
from app.services import cycle_service
from app.services.balance_service import calculate_accounts_total
from app.services.income_schedule import next_income_occurrences

ZERO = Decimal("0")


@dataclass(frozen=True)
class FlowEvent:
    date: date
    kind: str  # 'income' | 'card_due' | 'fixed_expense' | 'cycle_open_milestone'
    label: str
    # Con signo: positivo = entra dinero, negativo = sale. None = hito sin monto.
    amount: Optional[Decimal]
    reference_id: Optional[int] = None


@dataclass(frozen=True)
class FlowProjection:
    starting_balance: Decimal
    ending_balance: Decimal
    events: List[FlowEvent] = field(default_factory=list)
    deficit_risk: bool = False
    deficit_date: Optional[date] = None


def _income_events(session: Session, user_id: int, as_of: date, until: date) -> List[FlowEvent]:
    stmt = select(Income).where(Income.user_id == user_id, Income.is_active.is_(True))
    events: List[FlowEvent] = []
    for income in session.execute(stmt).scalars():
        # Suficientes ocurrencias para cubrir cualquier ventana razonable (90 días
        # con ingresos mensuales caben en 4; se corta por fecha de todos modos.
        occurrences = next_income_occurrences(income, as_of, count=8)
        for occ in occurrences:
            if occ > until:
                break
            events.append(
                FlowEvent(date=occ, kind="income", label=income.name, amount=income.amount, reference_id=income.id)
            )
    return events


def _card_due_events(session: Session, user_id: int, as_of: date, until: date) -> List[FlowEvent]:
    stmt = (
        select(BillingCycle, CreditCard)
        .join(CreditCard, BillingCycle.credit_card_id == CreditCard.id)
        .where(CreditCard.user_id == user_id)
    )
    events: List[FlowEvent] = []
    for cycle, card in session.execute(stmt).all():
        if cycle.status in (CycleStatus.CLOSED, CycleStatus.PARTIALLY_PAID):
            if as_of <= cycle.due_date <= until:
                remaining = cycle.total_amount - cycle.paid_amount
                if remaining > ZERO:
                    events.append(
                        FlowEvent(
                            date=cycle.due_date,
                            kind="card_due",
                            label=f"Pago {card.name}",
                            amount=-remaining,
                            reference_id=cycle.id,
                        )
                    )
        elif cycle.status == CycleStatus.OPEN:
            # Hito sin monto: el corte de un ciclo abierto no mueve dinero (regla 4.3).
            if as_of <= cycle.end_date <= until:
                events.append(
                    FlowEvent(date=cycle.end_date, kind="cycle_open_milestone", label=f"Corte {card.name}", amount=None, reference_id=cycle.id)
                )
    return events


def _fixed_expense_events(session: Session, user_id: int, as_of: date, until: date) -> List[FlowEvent]:
    stmt = select(FixedExpense).where(FixedExpense.user_id == user_id, FixedExpense.is_active.is_(True))
    events: List[FlowEvent] = []
    for fixed in session.execute(stmt).scalars():
        year, month = as_of.year, as_of.month
        # Recorre mes a mes hasta pasar `until` (igual patrón que balance_service).
        while date(year, month, 1) <= until:
            candidate = resolve_day_of_month(year, month, fixed.day_of_month)
            if as_of <= candidate <= until:
                events.append(
                    FlowEvent(date=candidate, kind="fixed_expense", label=fixed.name, amount=-fixed.amount, reference_id=fixed.id)
                )
            year, month = add_months(year, month, 1)
    return events


def _installment_due_dates(card: CreditCard, plan: InstallmentPlan) -> List[date]:
    """Fecha de vencimiento de cada una de las `months_total` mensualidades,
    caminando ciclo por ciclo desde `plan.start_date` (pura, sin DB: usa
    resolve_cycle_bounds tal como lo hace cycle_service.generate_cycles).
    """
    dues: List[date] = []
    reference = plan.start_date
    for _ in range(plan.months_total):
        bounds = cycle_service.resolve_cycle_bounds(card.statement_day, card.payment_term_days, reference)
        dues.append(bounds.due)
        reference = bounds.end
    return dues


def _installment_events(session: Session, user_id: int, as_of: date, until: date) -> List[FlowEvent]:
    stmt = (
        select(InstallmentPlan, CreditCard)
        .join(CreditCard, InstallmentPlan.credit_card_id == CreditCard.id)
        .where(CreditCard.user_id == user_id)
    )
    events: List[FlowEvent] = []
    for plan, card in session.execute(stmt).all():
        if plan.months_paid >= plan.months_total:
            continue
        due_dates = _installment_due_dates(card, plan)
        remaining_due_dates = due_dates[plan.months_paid :]
        for due in remaining_due_dates:
            if as_of <= due <= until:
                events.append(
                    FlowEvent(
                        date=due,
                        kind="installment",
                        label=f"{plan.description} ({card.name})",
                        amount=-plan.monthly_amount,
                        reference_id=plan.id,
                    )
                )
    return events


def project(session: Session, user_id: int, days: int, as_of: Optional[date] = None) -> FlowProjection:
    as_of = as_of or date.today()
    until = as_of + timedelta(days=days)

    events = (
        _income_events(session, user_id, as_of, until)
        + _card_due_events(session, user_id, as_of, until)
        + _fixed_expense_events(session, user_id, as_of, until)
        + _installment_events(session, user_id, as_of, until)
    )
    events.sort(key=lambda e: (e.date, e.kind))

    starting_balance = calculate_accounts_total(session, user_id)
    running = starting_balance
    deficit_date: Optional[date] = None
    for event in events:
        if event.amount is None:
            continue
        running += event.amount
        if running < ZERO and deficit_date is None:
            deficit_date = event.date

    return FlowProjection(
        starting_balance=starting_balance,
        ending_balance=running,
        events=events,
        deficit_risk=deficit_date is not None,
        deficit_date=deficit_date,
    )


def group_events_by_week(events: List[FlowEvent], as_of: date, days: int):
    """Agrupa en semanas [as_of, as_of+7), [as_of+7, as_of+14), ... (índice 0, 1, 2, ...).

    Incluye TODAS las semanas de la ventana (`days`), aunque no tengan eventos:
    si se omitieran las vacías, la numeración salta (ej. "Semana 1" y "Semana 2"
    sin eventos desaparecen y el timeline arranca directo en "Semana 3"), lo
    cual es confuso — el índice de una semana visible ya no corresponde a su
    posición real en el calendario.

    Los textos de presentación ("Esta semana", "Próxima semana") son responsabilidad
    de la capa de API/serialización, no de este servicio.
    """
    buckets: dict = {}
    for event in events:
        week_index = (event.date - as_of).days // 7
        buckets.setdefault(week_index, []).append(event)
    total_weeks = (days - 1) // 7 + 1
    return [
        {
            "week_index": idx,
            "start": as_of + timedelta(days=idx * 7),
            "end": as_of + timedelta(days=idx * 7 + 6),
            "events": buckets.get(idx, []),
        }
        for idx in range(total_weeks)
    ]
