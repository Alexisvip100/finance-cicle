from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.account import Account
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.credit_card import CreditCard
from app.models.payment import Payment, PaymentSource
from app.models.savings_allocation import SavingsAllocation
from app.models.user import User
from app.schemas.payment import AllocationCreate, AllocationRead, PaymentCreate, PaymentRead

router = APIRouter(tags=["payments"])

ZERO = Decimal("0")


def _get_owned_card(db: Session, user: User, card_id: int) -> CreditCard:
    card = db.get(CreditCard, card_id)
    if card is None or card.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarjeta no encontrada")
    return card


def _get_payable_cycle(db: Session, card: CreditCard, billing_cycle_id: int) -> BillingCycle:
    cycle = db.get(BillingCycle, billing_cycle_id)
    if cycle is None or cycle.credit_card_id != card.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciclo no encontrado")
    if cycle.status not in (CycleStatus.CLOSED, CycleStatus.PARTIALLY_PAID):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede pagar un ciclo cerrado (CLOSED o PARTIALLY_PAID)",
        )
    return cycle


@router.post("/cards/{card_id}/payments", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
def create_payment(
    card_id: int,
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = _get_owned_card(db, user, card_id)
    cycle = _get_payable_cycle(db, card, payload.billing_cycle_id)

    remaining = cycle.total_amount - cycle.paid_amount
    if payload.amount <= ZERO or payload.amount > remaining:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El monto debe ser mayor a 0 y no exceder lo pendiente ({remaining})",
        )

    if payload.source_type == PaymentSource.ACCOUNT:
        if payload.source_account_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falta source_account_id")
        account = db.get(Account, payload.source_account_id)
        if account is None or account.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")
        account.balance -= payload.amount
    else:
        # ALLOCATION: el dinero YA vive en la(s) cuenta(s) que lo apartaron —
        # pagar desde ahí sigue moviendo dinero real de esas cuentas (regla
        # 4.6/4.2: por eso disponible_real no cambia: accounts_total baja lo
        # mismo que baja committed). Se consumen las allocations más viejas
        # primero, hasta cubrir `amount`.
        alloc_stmt = (
            select(SavingsAllocation)
            .where(SavingsAllocation.billing_cycle_id == cycle.id)
            .order_by(SavingsAllocation.created_at.asc())
        )
        allocations = list(db.execute(alloc_stmt).scalars())
        available = sum((a.amount for a in allocations), start=ZERO)
        if payload.amount > available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El apartado disponible ({available}) es menor al monto a pagar",
            )
        remaining_to_consume = payload.amount
        for allocation in allocations:
            if remaining_to_consume <= ZERO:
                break
            consumed = min(allocation.amount, remaining_to_consume)
            source_account = db.get(Account, allocation.source_account_id)
            if source_account is not None:
                source_account.balance -= consumed
            allocation.amount -= consumed
            remaining_to_consume -= consumed
            if allocation.amount <= ZERO:
                db.delete(allocation)

    cycle.paid_amount += payload.amount
    cycle.status = CycleStatus.PAID if cycle.paid_amount >= cycle.total_amount else CycleStatus.PARTIALLY_PAID

    payment = Payment(
        billing_cycle_id=cycle.id,
        amount=payload.amount,
        payment_date=date.today(),
        source_type=payload.source_type,
        source_account_id=payload.source_account_id if payload.source_type == PaymentSource.ACCOUNT else None,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.post("/cards/{card_id}/allocations", response_model=AllocationRead, status_code=status.HTTP_201_CREATED)
def create_allocation(
    card_id: int,
    payload: AllocationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = _get_owned_card(db, user, card_id)
    cycle = db.get(BillingCycle, payload.billing_cycle_id)
    if cycle is None or cycle.credit_card_id != card.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciclo no encontrado")

    account = db.get(Account, payload.source_account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")

    # Caso de prueba #7: apartar más que el ciclo se PERMITE (solo se advertiría
    # en el frontend); aquí no se rechaza.
    allocation = SavingsAllocation(
        credit_card_id=card.id,
        billing_cycle_id=cycle.id,
        amount=payload.amount,
        source_account_id=account.id,
    )
    db.add(allocation)
    db.commit()
    db.refresh(allocation)
    return allocation


@router.delete("/allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation(
    allocation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    allocation = db.get(SavingsAllocation, allocation_id)
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apartado no encontrado")
    account = db.get(Account, allocation.source_account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apartado no encontrado")
    # Retirar del apartado no mueve dinero real: nunca se decrementó al apartar.
    db.delete(allocation)
    db.commit()
