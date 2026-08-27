from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.credit_card import BillingCycleRead


# ---- /dashboard ----------------------------------------------------------


class UpcomingOutflow(BaseModel):
    date: date
    kind: str
    label: str
    amount: Decimal


class DashboardCardSummary(BaseModel):
    id: int
    name: str
    current_cycle: Optional[BillingCycleRead] = None
    pending_cycle: Optional[BillingCycleRead] = None


class DashboardResponse(BaseModel):
    available: Decimal
    accounts_total: Decimal
    committed: Decimal
    pending_fixed: Decimal
    next_income_date: Optional[date]
    upcoming_outflows: List[UpcomingOutflow]
    cards: List[DashboardCardSummary]


# ---- /flow -----------------------------------------------------------------


class FlowEventRead(BaseModel):
    date: date
    kind: str
    label: str
    amount: Optional[Decimal]
    reference_id: Optional[int]


class FlowWeekBucket(BaseModel):
    week_index: int
    start: date
    end: date
    events: List[FlowEventRead]


class FlowResponse(BaseModel):
    as_of: date
    until: date
    starting_balance: Decimal
    ending_balance: Decimal
    deficit_risk: bool
    deficit_date: Optional[date]
    weeks: List[FlowWeekBucket]


# ---- /budget -----------------------------------------------------------------


class CategoryBudgetRead(BaseModel):
    category_id: Optional[int]
    category_name: str
    monthly_limit: Optional[Decimal]
    spent: Decimal
    credit_spent: Decimal
    credit_pending: Decimal
    created_at: Optional[datetime]


class BudgetResponse(BaseModel):
    month: str
    categories: List[CategoryBudgetRead]
    total_spent: Decimal
    spending_goal: Optional[Decimal]
    income_this_month: Decimal
    projected_savings: Decimal
