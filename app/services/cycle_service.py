"""cycle_service: resolución de ciclos de facturación.

Es el corazón del sistema (ver spec §11): si esto falla, todo lo demás falla
(disponible real, flujo, presupuesto). Por eso las funciones puras de fecha
(resolve_statement_date, resolve_cycle_bounds) están separadas de las funciones
que tocan la base de datos (get_or_create_cycle, generate_cycles, ...): las
primeras se prueban sin ninguna infraestructura, con datos, no con mocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dates import add_months, resolve_day_of_month
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction

DEFAULT_MONTHS_AHEAD = 3


@dataclass(frozen=True)
class CycleBounds:
    start: date
    end: date
    due: date


def resolve_statement_date(year: int, month: int, statement_day: int) -> date:
    """Regla 4.1 / caso de prueba #2: si `statement_day` no existe en ese mes
    (31 en un mes de 30, o 29/30/31 en febrero), se usa el último día real.
    Delgado sobre app.core.dates.resolve_day_of_month (nombre conservado para
    no romper los tests/llamadas existentes de cycle_service).
    """
    return resolve_day_of_month(year, month, statement_day)


def resolve_cycle_bounds(statement_day: int, payment_term_days: int, reference_date: date) -> CycleBounds:
    """Dado el día de corte de una tarjeta y una fecha (típicamente la fecha de
    una compra), devuelve el ciclo al que pertenece esa fecha.

    Regla clave (4.1): el día del corte pertenece al ciclo que ABRE ese día, no
    al que cierra. Por eso la comparación es `reference_date < corte_de_este_mes`
    para decidir si aún estamos en el ciclo anterior.
    """
    this_month_statement = resolve_statement_date(reference_date.year, reference_date.month, statement_day)

    if reference_date < this_month_statement:
        prev_year, prev_month = add_months(reference_date.year, reference_date.month, -1)
        start = resolve_statement_date(prev_year, prev_month, statement_day)
        end = this_month_statement
    else:
        start = this_month_statement
        next_year, next_month = add_months(reference_date.year, reference_date.month, 1)
        end = resolve_statement_date(next_year, next_month, statement_day)

    due = end + timedelta(days=payment_term_days)
    return CycleBounds(start=start, end=end, due=due)


def _get_cycle_by_start(session: Session, credit_card_id: int, start: date) -> Optional[BillingCycle]:
    stmt = select(BillingCycle).where(
        BillingCycle.credit_card_id == credit_card_id,
        BillingCycle.start_date == start,
    )
    return session.execute(stmt).scalar_one_or_none()


def get_or_create_cycle(session: Session, card: CreditCard, reference_date: date) -> BillingCycle:
    """Idempotente: si el ciclo que cubre `reference_date` ya existe, lo regresa;
    si no, lo crea como OPEN. Es lo que usa el endpoint POST /transactions al
    registrar un gasto con tarjeta (regla 4.6 y caso de prueba #10).
    """
    bounds = resolve_cycle_bounds(card.statement_day, card.payment_term_days, reference_date)
    existing = _get_cycle_by_start(session, card.id, bounds.start)
    if existing is not None:
        return existing

    cycle = BillingCycle(
        credit_card_id=card.id,
        start_date=bounds.start,
        end_date=bounds.end,
        due_date=bounds.due,
        status=CycleStatus.OPEN,
        total_amount=0,
        paid_amount=0,
    )
    session.add(cycle)
    session.flush()
    return cycle


def recalculate_cycle_total(session: Session, cycle: BillingCycle) -> None:
    """`total_amount` es derivado (spec §5): siempre debe poder recalcularse
    desde las transactions reales. Se llama tras insertar/eliminar una
    transacción de este ciclo (caso de prueba #11).
    """
    stmt = select(Transaction).where(Transaction.billing_cycle_id == cycle.id)
    total = sum((t.amount for t in session.execute(stmt).scalars()), start=Decimal("0"))
    cycle.total_amount = total
    session.flush()


def generate_cycles(
    session: Session,
    card: CreditCard,
    months_ahead: int = DEFAULT_MONTHS_AHEAD,
    today: Optional[date] = None,
) -> List[BillingCycle]:
    """Precalcula los ciclos de una tarjeta desde su ciclo actual hasta
    `months_ahead` ciclos hacia adelante. Idempotente: no duplica ciclos que
    ya existan (constraint uq_billing_cycle_card_start).

    `today` es inyectable (igual que en close_due_cycles) para que los tests
    no dependan del reloj real de la máquina.
    """
    created: List[BillingCycle] = []
    reference = today or date.today()
    for _ in range(months_ahead + 1):
        bounds = resolve_cycle_bounds(card.statement_day, card.payment_term_days, reference)
        existing = _get_cycle_by_start(session, card.id, bounds.start)
        if existing is None:
            cycle = BillingCycle(
                credit_card_id=card.id,
                start_date=bounds.start,
                end_date=bounds.end,
                due_date=bounds.due,
                status=CycleStatus.OPEN,
                total_amount=0,
                paid_amount=0,
            )
            session.add(cycle)
            created.append(cycle)
        # Avanza al siguiente ciclo usando un día dentro de él como referencia.
        reference = bounds.end
    session.flush()
    return created


def close_due_cycles(session: Session, today: Optional[date] = None) -> List[BillingCycle]:
    """Job diario (spec §7 jobs/): cierra los ciclos OPEN cuya fecha de fin ya
    pasó, fija su total_amount definitivo, y genera el siguiente ciclo de esa
    tarjeta para mantener la ventana de `months_ahead` completa.
    """
    today = today or date.today()
    stmt = select(BillingCycle).where(
        BillingCycle.status == CycleStatus.OPEN,
        BillingCycle.end_date <= today,
    )
    due_cycles = list(session.execute(stmt).scalars())

    for cycle in due_cycles:
        recalculate_cycle_total(session, cycle)
        cycle.status = CycleStatus.CLOSED

    session.flush()
    return due_cycles


def regenerate_future_cycles(
    session: Session,
    card: CreditCard,
    months_ahead: int = DEFAULT_MONTHS_AHEAD,
    today: Optional[date] = None,
) -> None:
    """Caso de prueba #12: al cambiar `statement_day`/`payment_term_days` de una
    tarjeta, los ciclos OPEN futuros (que aún no representan deuda exigible) se
    borran y se regeneran con la nueva configuración. Los CLOSED/PAID/
    PARTIALLY_PAID no se toca — ya son deuda histórica real.
    """
    stmt = select(BillingCycle).where(
        BillingCycle.credit_card_id == card.id,
        BillingCycle.status == CycleStatus.OPEN,
    )
    for cycle in session.execute(stmt).scalars():
        session.delete(cycle)
    session.flush()
    generate_cycles(session, card, months_ahead=months_ahead, today=today)
