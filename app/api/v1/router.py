from fastapi import APIRouter

from app.api.v1 import (
    accounts,
    aggregates,
    auth,
    cards,
    categories,
    fixed_expenses,
    incomes,
    payments,
    transactions,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(cards.router)
api_router.include_router(transactions.router)
api_router.include_router(payments.router)
api_router.include_router(categories.router)
api_router.include_router(fixed_expenses.router)
api_router.include_router(incomes.router)
api_router.include_router(aggregates.router)
