from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.account import Account
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.installment_plan import InstallmentPlan
from app.models.transaction import PaymentMethod, Transaction
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionRead
from app.services import cycle_service

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _get_owned(db: Session, model, obj_id: int, user_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} no encontrada")
    return obj


@router.post("", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    category = (
        _get_owned(db, Category, payload.category_id, user.id, "Categoría")
        if payload.category_id is not None
        else None
    )

    if payload.payment_method == PaymentMethod.CREDIT:
        card = _get_owned(db, CreditCard, payload.credit_card_id, user.id, "Tarjeta")

        if payload.installment_months:
            # MSI: el monto completo se devenga aquí (regla 4.5); las N
            # mensualidades futuras las proyecta flow_service desde
            # InstallmentPlan — no se crea una Transaction por cada una
            # (evitaría contar el gasto N veces en el presupuesto).
            first_due = cycle_service.resolve_cycle_bounds(
                card.statement_day, card.payment_term_days, payload.transaction_date
            ).due
            transaction = Transaction(
                user_id=user.id,
                amount=payload.amount,
                category_id=category.id if category else None,
                description=payload.description,
                transaction_date=payload.transaction_date,
                payment_method=payload.payment_method,
                credit_card_id=card.id,
                billing_cycle_id=None,
                cash_flow_date=first_due,
            )
            db.add(transaction)
            db.flush()

            monthly_amount = (payload.amount / payload.installment_months).quantize(Decimal("0.01"))
            plan = InstallmentPlan(
                credit_card_id=card.id,
                transaction_id=transaction.id,
                description=payload.description,
                total_amount=payload.amount,
                months_total=payload.installment_months,
                months_paid=0,
                monthly_amount=monthly_amount,
                start_date=payload.transaction_date,
            )
            db.add(plan)
            db.flush()
        else:
            cycle = cycle_service.get_or_create_cycle(db, card, payload.transaction_date)
            # Un ciclo que ya no está OPEN tiene un monto ya fijo (CLOSED/
            # PARTIALLY_PAID/PAID) — a veces ni siquiera derivado de
            # transacciones reales (ej. la deuda inicial capturada al crear
            # la tarjeta). Sumarle una compra ahí con recalculate_cycle_total
            # pisaría ese monto en vez de sumarlo. Se bloquea: la fecha debe
            # caer en el ciclo actual (abierto).
            if cycle.status != CycleStatus.OPEN:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Esa fecha cae en un ciclo que ya cerró. Usa una fecha dentro del ciclo actual (o del que corresponda si aún está abierto).",
                )
            transaction = Transaction(
                user_id=user.id,
                amount=payload.amount,
                category_id=category.id if category else None,
                description=payload.description,
                transaction_date=payload.transaction_date,
                payment_method=payload.payment_method,
                credit_card_id=card.id,
                billing_cycle_id=cycle.id,
                cash_flow_date=cycle.due_date,
            )
            db.add(transaction)
            db.flush()
            cycle_service.recalculate_cycle_total(db, cycle)
    else:
        account = _get_owned(db, Account, payload.account_id, user.id, "Cuenta")
        transaction = Transaction(
            user_id=user.id,
            amount=payload.amount,
            category_id=category.id if category else None,
            description=payload.description,
            transaction_date=payload.transaction_date,
            payment_method=payload.payment_method,
            account_id=account.id,
            billing_cycle_id=None,
            cash_flow_date=payload.transaction_date,
        )
        account.balance -= payload.amount
        db.add(transaction)
        db.flush()

    db.commit()
    db.refresh(transaction)
    return transaction


@router.get("", response_model=List[TransactionRead])
def list_transactions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    category_id: Optional[int] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    payment_method: Optional[PaymentMethod] = Query(default=None),
    account_id: Optional[int] = Query(default=None),
    credit_card_id: Optional[int] = Query(default=None),
    fixed_expense_id: Optional[int] = Query(default=None),
    only_fixed_expenses: bool = Query(default=False),
):
    stmt = select(Transaction).where(Transaction.user_id == user.id)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if from_date is not None:
        stmt = stmt.where(Transaction.transaction_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(Transaction.transaction_date <= to_date)
    if payment_method is not None:
        stmt = stmt.where(Transaction.payment_method == payment_method)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if credit_card_id is not None:
        stmt = stmt.where(Transaction.credit_card_id == credit_card_id)
    if fixed_expense_id is not None:
        stmt = stmt.where(Transaction.fixed_expense_id == fixed_expense_id)
    if only_fixed_expenses:
        stmt = stmt.where(Transaction.fixed_expense_id.is_not(None))
    stmt = stmt.order_by(Transaction.transaction_date.desc())
    return list(db.execute(stmt).scalars())


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    transaction = _get_owned(db, Transaction, transaction_id, user.id, "Movimiento")

    # Si esta transacción originó un plan MSI, el plan deja de tener sentido sin ella.
    plan_stmt = select(InstallmentPlan).where(InstallmentPlan.transaction_id == transaction.id)
    plan = db.execute(plan_stmt).scalar_one_or_none()
    if plan is not None:
        db.delete(plan)

    if transaction.payment_method != PaymentMethod.CREDIT and transaction.account_id is not None:
        account = db.get(Account, transaction.account_id)
        if account is not None:
            account.balance += transaction.amount

    cycle_id = transaction.billing_cycle_id
    db.delete(transaction)
    db.flush()

    # Caso de prueba #11: borrar una transacción de un ciclo (cerrado o no)
    # recalcula el monto del ciclo.
    if cycle_id is not None:
        cycle = db.get(BillingCycle, cycle_id)
        if cycle is not None:
            cycle_service.recalculate_cycle_total(db, cycle)

    db.commit()
