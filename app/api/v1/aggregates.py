from datetime import date, timedelta
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.credit_card import CreditCard
from app.models.user import User
from app.schemas.aggregates import (
    BudgetResponse,
    CategoryBudgetRead,
    DashboardCardSummary,
    DashboardResponse,
    FlowEventRead,
    FlowResponse,
    FlowWeekBucket,
    UpcomingOutflow,
)
from app.schemas.credit_card import BillingCycleRead
from app.services import balance_service, budget_service, cycle_service, flow_service

router = APIRouter(tags=["aggregates"])

DASHBOARD_HORIZON_DAYS = 14
ALLOWED_FLOW_DAYS = {30, 60, 90}


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    today = date.today()
    breakdown = balance_service.calculate_available(db, user.id, as_of=today)

    projection = flow_service.project(db, user.id, days=DASHBOARD_HORIZON_DAYS, as_of=today)
    outflows = [
        UpcomingOutflow(date=e.date, kind=e.kind, label=e.label, amount=e.amount)
        for e in projection.events
        if e.kind in ("fixed_expense", "card_due", "installment") and e.amount is not None
    ]

    cards_stmt = select(CreditCard).where(CreditCard.user_id == user.id)
    card_summaries: List[DashboardCardSummary] = []
    for card in db.execute(cards_stmt).scalars():
        current_cycle = cycle_service.get_or_create_cycle(db, card, today)
        pending_cycle = db.execute(
            select(BillingCycle)
            .where(
                BillingCycle.credit_card_id == card.id,
                BillingCycle.status.in_((CycleStatus.CLOSED, CycleStatus.PARTIALLY_PAID)),
            )
            .order_by(BillingCycle.due_date.asc())
        ).scalars().first()

        card_summaries.append(
            DashboardCardSummary(
                id=card.id,
                name=card.name,
                current_cycle=BillingCycleRead.model_validate(current_cycle),
                pending_cycle=BillingCycleRead.model_validate(pending_cycle) if pending_cycle else None,
            )
        )
    db.commit()

    return DashboardResponse(
        available=breakdown.available,
        accounts_total=breakdown.accounts_total,
        committed=breakdown.committed,
        pending_fixed=breakdown.pending_fixed,
        next_income_date=breakdown.next_income_date,
        upcoming_outflows=sorted(outflows, key=lambda o: o.date),
        cards=card_summaries,
    )


@router.get("/flow", response_model=FlowResponse)
def get_flow(
    days: int = Query(default=30),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if days not in ALLOWED_FLOW_DAYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="days debe ser 30, 60 o 90")

    today = date.today()
    projection = flow_service.project(db, user.id, days=days, as_of=today)
    grouped = flow_service.group_events_by_week(projection.events, as_of=today, days=days)

    weeks = [
        FlowWeekBucket(
            week_index=bucket["week_index"],
            start=bucket["start"],
            end=bucket["end"],
            events=[
                FlowEventRead(date=e.date, kind=e.kind, label=e.label, amount=e.amount, reference_id=e.reference_id)
                for e in bucket["events"]
            ],
        )
        for bucket in grouped
    ]

    return FlowResponse(
        as_of=today,
        until=today + timedelta(days=days),
        starting_balance=projection.starting_balance,
        ending_balance=projection.ending_balance,
        deficit_risk=projection.deficit_risk,
        deficit_date=projection.deficit_date,
        weeks=weeks,
    )


@router.get("/budget", response_model=BudgetResponse)
def get_budget(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    summaries = budget_service.month_summary(db, user.id, month)
    total_spent = sum((s.spent for s in summaries), start=Decimal("0"))
    income_this_month = budget_service.monthly_income_total(db, user.id)
    return BudgetResponse(
        month=month,
        categories=[
            CategoryBudgetRead(
                category_id=s.category_id,
                category_name=s.category_name,
                monthly_limit=s.monthly_limit,
                spent=s.spent,
                credit_spent=s.credit_spent,
                credit_pending=s.credit_pending,
                created_at=s.created_at,
            )
            for s in summaries
        ],
        total_spent=total_spent,
        spending_goal=user.monthly_spending_goal,
        income_this_month=income_this_month,
        projected_savings=income_this_month - total_spent,
    )
