from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.category import Category
from app.models.fixed_expense import FixedExpense
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])


def _get_owned(db: Session, user: User, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None or category.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoría no encontrada")
    return category


@router.get("", response_model=List[CategoryRead])
def list_categories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Category).where(Category.user_id == user.id)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    category = Category(user_id=user.id, **payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.get("/{category_id}", response_model=CategoryRead)
def get_category(category_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _get_owned(db, user, category_id)


@router.patch("/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    category = _get_owned(db, user, category_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    category = _get_owned(db, user, category_id)

    has_transactions = db.execute(
        select(Transaction.id).where(Transaction.category_id == category.id).limit(1)
    ).first()
    has_fixed_expenses = db.execute(
        select(FixedExpense.id).where(FixedExpense.category_id == category.id).limit(1)
    ).first()
    if has_transactions is not None or has_fixed_expenses is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede borrar una categoría con gastos o gastos fijos registrados.",
        )

    db.delete(category)
    db.commit()
