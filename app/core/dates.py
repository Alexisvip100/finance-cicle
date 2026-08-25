"""Aritmética de fechas compartida entre cycle_service, balance_service y
flow_service. Vive aquí (no en cycle_service) porque balance_service también
la necesita para resolver el sentinel LAST_DAY de los ingresos (regla 4.4) sin
crear una dependencia de flow/balance hacia cycle_service.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Tuple, Union


def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(year: int, month: int, delta: int) -> Tuple[int, int]:
    """Aritmética de año/mes sin importar el día (el día se resuelve aparte,
    por resolve_day_of_month, que sabe clamear/resolver LAST_DAY)."""
    zero_based = (month - 1) + delta
    new_year = year + zero_based // 12
    new_month = zero_based % 12 + 1
    return new_year, new_month


def resolve_day_of_month(year: int, month: int, day_or_last: Union[int, str]) -> date:
    """`day_or_last` es un día 1-31, o el sentinel LAST_DAY (ver app.models.income).
    Si es un entero que no existe en ese mes, se clamea al último día real
    (misma regla que el día de corte de una tarjeta, caso de prueba #2).
    """
    last_day = last_day_of_month(year, month)
    if isinstance(day_or_last, str):
        day = last_day
    else:
        day = min(day_or_last, last_day)
    return date(year, month, day)


WEEKDAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def resolve_nth_weekday(year: int, month: int, week: str, weekday_code: str) -> date:
    """`week` es "1".."4" o "LAST"; `weekday_code` es uno de WEEKDAY_CODES.
    Regla 4.4 extendida: paydays tipo "el último viernes del mes" (no un día
    fijo del mes, sino una semana + día de la semana — ver Income.payment_days).

    Si la semana pedida no existe en ese mes (ej. "5ta semana", o una "4ta"
    que cae fuera), cae de vuelta a la última ocurrencia de ese día de la
    semana — igual que resolve_day_of_month clamea un día fuera de rango.
    """
    weekday_index = WEEKDAY_CODES.index(weekday_code)
    if week == "LAST":
        last_day = last_day_of_month(year, month)
        candidate = date(year, month, last_day)
        offset = (candidate.weekday() - weekday_index) % 7
        return candidate - timedelta(days=offset)

    first_day = date(year, month, 1)
    offset = (weekday_index - first_day.weekday()) % 7
    candidate = first_day + timedelta(days=offset + (int(week) - 1) * 7)
    if candidate.month != month:
        return resolve_nth_weekday(year, month, "LAST", weekday_code)
    return candidate


def adjust_to_preceding_friday_if_weekend(d: date) -> date:
    """Nómina típica: si el día de pago cae sábado o domingo, se deposita el
    viernes anterior (no el lunes siguiente) — ver Income.payment_days,
    formato "D{día}-ADJ"."""
    if d.weekday() == 5:  # sábado
        return d - timedelta(days=1)
    if d.weekday() == 6:  # domingo
        return d - timedelta(days=2)
    return d
