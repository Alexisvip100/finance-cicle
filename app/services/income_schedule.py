"""Resolución de fechas de pago de ingresos (regla 4.4).

Tanto balance_service (próximo ingreso, para acotar "fijos pendientes") como
flow_service (proyección de ingresos futuros) necesitan esto, por eso vive
aparte y no dentro de ninguno de los dos.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from app.core.dates import (
    add_months,
    adjust_to_preceding_friday_if_weekend,
    resolve_day_of_month,
    resolve_nth_weekday,
)
from app.models.income import Income, IncomeFrequency, parse_day_adjusted, parse_week_weekday


def _resolve_payment_day(year: int, month: int, day_or_spec) -> date:
    """`day_or_spec` es un día 1-31, LAST_DAY, una "semana de pago" tipo
    "WLAST-FRI" (el último viernes del mes), o un día fijo ajustado tipo
    "D15-ADJ" (el 15, recorrido al viernes anterior si cae en fin de semana)
    — ver Income.payment_days."""
    if isinstance(day_or_spec, str):
        week_weekday = parse_week_weekday(day_or_spec)
        if week_weekday is not None:
            week, weekday_code = week_weekday
            return resolve_nth_weekday(year, month, week, weekday_code)
        day_adjusted = parse_day_adjusted(day_or_spec)
        if day_adjusted is not None:
            return adjust_to_preceding_friday_if_weekend(resolve_day_of_month(year, month, day_adjusted))
    return resolve_day_of_month(year, month, day_or_spec)


def next_income_occurrences(income: Income, after: date, count: int = 1) -> List[date]:
    """Regresa hasta `count` fechas de pago futuras (estrictamente > `after`).

    BIWEEKLY y MONTHLY usan el mismo algoritmo: `payment_days` ya contiene
    todos los días de pago del mes (ej. [15, LAST_DAY] o [1]); la frecuencia
    es solo descriptiva. VARIABLE no tiene fechas fijas — no se puede
    proyectar de forma determinista, así que regresa una lista vacía.
    """
    if income.frequency == IncomeFrequency.VARIABLE or not income.payment_days:
        return []

    occurrences: List[date] = []
    year, month = after.year, after.month
    # Tope de seguridad: nunca debería tardar más de un par de años en
    # encontrar `count` ocurrencias con pagos mensuales/quincenales reales.
    for _ in range(36):
        for day_or_spec in income.payment_days:
            candidate = _resolve_payment_day(year, month, day_or_spec)
            if candidate > after:
                occurrences.append(candidate)
        if len(occurrences) >= count:
            break
        year, month = add_months(year, month, 1)

    occurrences.sort()
    return occurrences[:count]


def next_income_date(incomes: List[Income], after: date) -> Optional[date]:
    """La fecha de pago más próxima entre varios ingresos activos (o None si
    ninguno tiene una fecha resoluble, ej. todos son VARIABLE).
    """
    candidates = []
    for income in incomes:
        occ = next_income_occurrences(income, after, count=1)
        if occ:
            candidates.append(occ[0])
    return min(candidates) if candidates else None
