from datetime import date, timedelta
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.credit_card import CreditCard
from app.models.installment_plan import InstallmentPlan
from app.models.savings_allocation import SavingsAllocation
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.credit_card import (
    BillingCycleRead,
    CreditCardCreate,
    CreditCardDetail,
    CreditCardRead,
    CreditCardUpdate,
    InstallmentPlanRead,
)
from app.schemas.transaction import TransactionRead
from app.services import cycle_service

router = APIRouter(prefix="/cards", tags=["cards"])

ZERO = Decimal("0")
# Configuración de tarjeta que, al cambiar, invalida los ciclos OPEN futuros
# (caso de prueba #12) — los CLOSED/PAID/PARTIALLY_PAID nunca se tocan.
CYCLE_CONFIG_FIELDS = {"statement_day", "payment_term_days"}


def _get_owned_card(db: Session, user: User, card_id: int) -> CreditCard:
    card = db.get(CreditCard, card_id)
    if card is None or card.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarjeta no encontrada")
    return card


def _build_detail(db: Session, card: CreditCard) -> CreditCardDetail:
    today = date.today()
    current_cycle = cycle_service.get_or_create_cycle(db, card, today)
    db.commit()

    pending_stmt = (
        select(BillingCycle)
        .where(
            BillingCycle.credit_card_id == card.id,
            BillingCycle.status.in_((CycleStatus.CLOSED, CycleStatus.PARTIALLY_PAID)),
        )
        .order_by(BillingCycle.due_date.asc())
    )
    pending_cycle = db.execute(pending_stmt).scalars().first()

    allocated = ZERO
    if pending_cycle is not None:
        alloc_stmt = select(SavingsAllocation).where(SavingsAllocation.billing_cycle_id == pending_cycle.id)
        allocated = sum((a.amount for a in db.execute(alloc_stmt).scalars()), start=ZERO)

    plans_stmt = select(InstallmentPlan).where(InstallmentPlan.credit_card_id == card.id)
    active_plans = [p for p in db.execute(plans_stmt).scalars() if p.months_paid < p.months_total]

    # Crédito disponible = límite - todo lo que aún ocupa ese límite: el ciclo
    # actual (OPEN, aunque todavía no sea "comprometido" para disponible_real
    # — el banco ya te descontó ese crédito en el momento de la compra) + lo
    # que falta de ciclos CLOSED/PARTIALLY_PAID + lo que falta de los MSI
    # (esos NUNCA entran al total_amount de ningún ciclo, ver transactions.py).
    debt_stmt = select(BillingCycle).where(
        BillingCycle.credit_card_id == card.id, BillingCycle.status != CycleStatus.PAID
    )
    cycles_debt = sum(
        (c.total_amount - c.paid_amount for c in db.execute(debt_stmt).scalars()), start=ZERO
    )
    msi_debt = sum((p.monthly_amount * (p.months_total - p.months_paid) for p in active_plans), start=ZERO)
    available_credit = card.credit_limit - cycles_debt - msi_debt

    last_paid_cycle = None
    if pending_cycle is None:
        last_paid_stmt = (
            select(BillingCycle)
            .where(BillingCycle.credit_card_id == card.id, BillingCycle.status == CycleStatus.PAID)
            .order_by(BillingCycle.due_date.desc())
        )
        last_paid_cycle = db.execute(last_paid_stmt).scalars().first()

    return CreditCardDetail(
        **CreditCardRead.model_validate(card).model_dump(),
        current_cycle=BillingCycleRead.model_validate(current_cycle) if current_cycle else None,
        pending_cycle=BillingCycleRead.model_validate(pending_cycle) if pending_cycle else None,
        allocated_for_pending_cycle=allocated,
        installment_plans=[InstallmentPlanRead.model_validate(p) for p in active_plans],
        available_credit=available_credit,
        last_paid_cycle=BillingCycleRead.model_validate(last_paid_cycle) if last_paid_cycle else None,
    )


@router.get("", response_model=List[CreditCardRead])
def list_cards(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(CreditCard).where(CreditCard.user_id == user.id)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=CreditCardRead, status_code=status.HTTP_201_CREATED)
def create_card(payload: CreditCardCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = payload.model_dump(exclude={"initial_balance", "initial_due_date"})
    card = CreditCard(user_id=user.id, **data)
    db.add(card)
    db.flush()

    # Caso de prueba #8: deuda preexistente → un ciclo CLOSED inicial, calculado
    # hacia atrás desde `initial_due_date` con la config de corte/plazo de la tarjeta.
    # Se crea ANTES de generate_cycles (y no después) para que, si el ciclo
    # "actual" resuelve al mismo start_date que esta deuda inicial (due_date
    # cercano a hoy), generate_cycles lo detecte como ya existente y no intente
    # insertar un duplicado — eso violaba la unique constraint y tiraba toda
    # la creación de la tarjeta (nada se guardaba, ni siquiera la tarjeta).
    if payload.initial_balance is not None and payload.initial_due_date is not None:
        end_date = payload.initial_due_date - timedelta(days=payload.payment_term_days)
        bounds = cycle_service.resolve_cycle_bounds(
            payload.statement_day, payload.payment_term_days, end_date - timedelta(days=1)
        )
        db.add(
            BillingCycle(
                credit_card_id=card.id,
                start_date=bounds.start,
                end_date=bounds.end,
                due_date=payload.initial_due_date,
                status=CycleStatus.CLOSED,
                total_amount=payload.initial_balance,
                paid_amount=Decimal("0"),
            )
        )
        db.flush()

    # Precalcula el ciclo actual y los siguientes de inmediato: el usuario debe
    # ver "tu ciclo actual" y su fecha de pago en el momento de agregar la tarjeta.
    # Es idempotente por start_date, así que si la deuda inicial de arriba ya
    # ocupó el ciclo "actual", esto simplemente no lo duplica.
    cycle_service.generate_cycles(db, card, months_ahead=settings.cycle_months_ahead)

    db.commit()
    db.refresh(card)
    return card


@router.get("/{card_id}", response_model=CreditCardDetail)
def get_card_detail(card_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    card = _get_owned_card(db, user, card_id)
    return _build_detail(db, card)


@router.patch("/{card_id}", response_model=CreditCardRead)
def update_card(
    card_id: int,
    payload: CreditCardUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = _get_owned_card(db, user, card_id)
    updates = payload.model_dump(exclude_unset=True)
    cycle_config_changed = bool(CYCLE_CONFIG_FIELDS & updates.keys())

    for field, value in updates.items():
        setattr(card, field, value)
    db.flush()

    if cycle_config_changed:
        cycle_service.regenerate_future_cycles(db, card, months_ahead=settings.cycle_months_ahead)

    db.commit()
    db.refresh(card)
    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(card_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    card = _get_owned_card(db, user, card_id)
    has_history = db.execute(
        select(BillingCycle.id).where(BillingCycle.credit_card_id == card.id).limit(1)
    ).first()
    if has_history is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede borrar una tarjeta con ciclos/movimientos. Deberías desactivarla en su lugar.",
        )
    db.delete(card)
    db.commit()


@router.get("/{card_id}/cycles", response_model=List[BillingCycleRead])
def list_cycles(card_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    card = _get_owned_card(db, user, card_id)
    stmt = (
        select(BillingCycle)
        .where(BillingCycle.credit_card_id == card.id)
        .order_by(BillingCycle.start_date.asc())
    )
    return list(db.execute(stmt).scalars())


@router.get("/{card_id}/cycles/{cycle_id}/transactions", response_model=List[TransactionRead])
def list_cycle_transactions(
    card_id: int,
    cycle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = _get_owned_card(db, user, card_id)
    cycle = db.get(BillingCycle, cycle_id)
    if cycle is None or cycle.credit_card_id != card.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciclo no encontrado")

    stmt = select(Transaction).where(Transaction.billing_cycle_id == cycle.id).order_by(Transaction.transaction_date.asc())
    return list(db.execute(stmt).scalars())
