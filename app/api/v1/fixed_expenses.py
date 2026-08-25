from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.account import Account
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.fixed_expense import FixedExpense
from app.models.transaction import PaymentMethod, Transaction
from app.models.user import User
from app.schemas.fixed_expense import FixedExpenseCreate, FixedExpensePay, FixedExpenseRead, FixedExpenseUpdate
from app.schemas.transaction import TransactionRead
from app.services import cycle_service

router = APIRouter(prefix="/fixed-expenses", tags=["fixed-expenses"])


def _get_owned(db: Session, user: User, fixed_expense_id: int) -> FixedExpense:
    fixed = db.get(FixedExpense, fixed_expense_id)
    if fixed is None or fixed.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto fijo no encontrado")
    return fixed


def _validate_references(db: Session, user: User, payload: FixedExpenseCreate) -> None:
    category = db.get(Category, payload.category_id)
    if category is None or category.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoría no encontrada")
    if payload.account_id is not None:
        account = db.get(Account, payload.account_id)
        if account is None or account.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")
    if payload.credit_card_id is not None:
        card = db.get(CreditCard, payload.credit_card_id)
        if card is None or card.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarjeta no encontrada")


@router.get("", response_model=List[FixedExpenseRead])
def list_fixed_expenses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(FixedExpense).where(FixedExpense.user_id == user.id)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=FixedExpenseRead, status_code=status.HTTP_201_CREATED)
def create_fixed_expense(
    payload: FixedExpenseCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _validate_references(db, user, payload)
    fixed = FixedExpense(user_id=user.id, **payload.model_dump())
    db.add(fixed)
    db.commit()
    db.refresh(fixed)
    return fixed


@router.get("/{fixed_expense_id}", response_model=FixedExpenseRead)
def get_fixed_expense(
    fixed_expense_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _get_owned(db, user, fixed_expense_id)


@router.patch("/{fixed_expense_id}", response_model=FixedExpenseRead)
def update_fixed_expense(
    fixed_expense_id: int,
    payload: FixedExpenseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    fixed = _get_owned(db, user, fixed_expense_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(fixed, field, value)
    db.commit()
    db.refresh(fixed)
    return fixed


@router.delete("/{fixed_expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fixed_expense(
    fixed_expense_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    fixed = _get_owned(db, user, fixed_expense_id)
    db.delete(fixed)
    db.commit()


@router.post("/{fixed_expense_id}/pay", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def pay_fixed_expense(
    fixed_expense_id: int,
    payload: FixedExpensePay = FixedExpensePay(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Registra el gasto fijo del mes como una Transaction real (regla: solo
    definir el gasto fijo no lo hace aparecer como gastado — hay que marcarlo
    pagado). `fixed_expense_id` en la transacción resultante es lo que permite
    distinguirla en el historial y filtrar "solo gastos fijos"."""
    fixed = _get_owned(db, user, fixed_expense_id)
    if not fixed.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este gasto fijo está inactivo")

    transaction_date = payload.transaction_date or date.today()

    if fixed.credit_card_id is not None:
        card = db.get(CreditCard, fixed.credit_card_id)
        if card is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La tarjeta de este gasto fijo ya no existe")
        cycle = cycle_service.get_or_create_cycle(db, card, transaction_date)
        transaction = Transaction(
            user_id=user.id,
            amount=fixed.amount,
            category_id=fixed.category_id,
            description=fixed.name,
            transaction_date=transaction_date,
            payment_method=PaymentMethod.CREDIT,
            credit_card_id=card.id,
            billing_cycle_id=cycle.id,
            cash_flow_date=cycle.due_date,
            fixed_expense_id=fixed.id,
        )
        db.add(transaction)
        db.flush()
        cycle_service.recalculate_cycle_total(db, cycle)
    else:
        account = db.get(Account, fixed.account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta de este gasto fijo ya no existe")
        transaction = Transaction(
            user_id=user.id,
            amount=fixed.amount,
            category_id=fixed.category_id,
            description=fixed.name,
            transaction_date=transaction_date,
            payment_method=PaymentMethod(account.type.value),
            account_id=account.id,
            cash_flow_date=transaction_date,
            fixed_expense_id=fixed.id,
        )
        account.balance -= fixed.amount
        db.add(transaction)
        db.flush()

    db.commit()
    db.refresh(transaction)
    return transaction
