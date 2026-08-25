from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.account import Account
from app.models.fixed_expense import FixedExpense
from app.models.income import Income
from app.models.payment import Payment
from app.models.savings_allocation import SavingsAllocation
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _get_owned_account(db: Session, user: User, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")
    return account


@router.get("", response_model=List[AccountRead])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Account).where(Account.user_id == user.id)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = Account(user_id=user.id, **payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=AccountRead)
def get_account(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _get_owned_account(db, user, account_id)


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = _get_owned_account(db, user, account_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned_account(db, user, account_id)

    # Borrar una cuenta que todavía tiene referencias deja gastos fijos/pagos
    # colgando de un account_id inexistente (500 al usarlos después) — se
    # bloquea igual que con tarjetas (cycles) y categorías (gastos).
    references = [
        select(Transaction.id).where(Transaction.account_id == account.id).limit(1),
        select(FixedExpense.id).where(FixedExpense.account_id == account.id).limit(1),
        select(Income.id).where(Income.account_id == account.id).limit(1),
        select(Payment.id).where(Payment.source_account_id == account.id).limit(1),
        select(SavingsAllocation.id).where(SavingsAllocation.source_account_id == account.id).limit(1),
    ]
    if any(db.execute(stmt).first() is not None for stmt in references):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede borrar una cuenta con movimientos, ingresos o gastos fijos asociados.",
        )

    db.delete(account)
    db.commit()
