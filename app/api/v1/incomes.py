from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.account import Account
from app.models.income import Income
from app.models.income_receipt import IncomeReceipt
from app.models.user import User
from app.schemas.income import IncomeCreate, IncomeRead, IncomeUpdate
from app.schemas.income_receipt import IncomeReceiptCreate, IncomeReceiptRead

router = APIRouter(prefix="/incomes", tags=["incomes"])


def _get_owned(db: Session, user: User, income_id: int) -> Income:
    income = db.get(Income, income_id)
    if income is None or income.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingreso no encontrado")
    return income


@router.get("/receipts", response_model=List[IncomeReceiptRead])
def list_income_receipts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    income_id: Optional[int] = Query(default=None),
):
    stmt = select(IncomeReceipt).where(IncomeReceipt.user_id == user.id)
    if from_date is not None:
        stmt = stmt.where(IncomeReceipt.received_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(IncomeReceipt.received_date <= to_date)
    if income_id is not None:
        stmt = stmt.where(IncomeReceipt.income_id == income_id)
    stmt = stmt.order_by(IncomeReceipt.received_date.desc())
    return list(db.execute(stmt).scalars())


def _get_owned_receipt(db: Session, user: User, receipt_id: int) -> IncomeReceipt:
    receipt = db.get(IncomeReceipt, receipt_id)
    if receipt is None or receipt.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recibo no encontrado")
    return receipt


@router.delete("/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income_receipt(receipt_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Deshace un 'marcar pagado' por error: revierte el abono a la cuenta y
    borra el recibo."""
    receipt = _get_owned_receipt(db, user, receipt_id)
    account = db.get(Account, receipt.account_id)
    account.balance -= receipt.amount
    db.delete(receipt)
    db.commit()


@router.get("", response_model=List[IncomeRead])
def list_incomes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Income).where(Income.user_id == user.id)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=IncomeRead, status_code=status.HTTP_201_CREATED)
def create_income(payload: IncomeCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = db.get(Account, payload.account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")
    income = Income(user_id=user.id, **payload.model_dump())
    db.add(income)
    db.commit()
    db.refresh(income)
    return income


@router.get("/{income_id}", response_model=IncomeRead)
def get_income(income_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _get_owned(db, user, income_id)


@router.patch("/{income_id}", response_model=IncomeRead)
def update_income(
    income_id: int, payload: IncomeUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    income = _get_owned(db, user, income_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(income, field, value)
    db.commit()
    db.refresh(income)
    return income


@router.delete("/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income(income_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    income = _get_owned(db, user, income_id)
    db.delete(income)
    db.commit()


@router.post("/{income_id}/receive", response_model=IncomeReceiptRead, status_code=status.HTTP_201_CREATED)
def receive_income(
    income_id: int,
    payload: IncomeReceiptCreate = IncomeReceiptCreate(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Registra que este ingreso ya se cobró: abona la cuenta destino y deja
    un IncomeReceipt para poder filtrarlo después por día o mes."""
    income = _get_owned(db, user, income_id)
    if not income.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este ingreso está inactivo")

    account = db.get(Account, income.account_id)
    received_date = payload.received_date or date.today()
    amount = payload.amount if payload.amount is not None else income.amount

    receipt = IncomeReceipt(
        user_id=user.id,
        income_id=income.id,
        account_id=account.id,
        amount=amount,
        received_date=received_date,
    )
    account.balance += amount
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt
