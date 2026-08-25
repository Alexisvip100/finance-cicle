from datetime import date
from decimal import Decimal
from typing import List, Optional, Union

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models import Account, AccountType, Category, CreditCard, User
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.fixed_expense import FixedExpense
from app.models.income import Income, IncomeFrequency
from app.models.installment_plan import InstallmentPlan
from app.models.savings_allocation import SavingsAllocation
from app.models.transaction import PaymentMethod, Transaction


@pytest.fixture()
def session():
    """DB en memoria por test: aislada, rápida, sin requerir Postgres corriendo.
    La lógica de dominio no usa nada específico de un dialecto, así que esto
    prueba el mismo código que correrá contra PostgreSQL en producción.

    StaticPool + check_same_thread=False: una sola conexión compartida. Sin
    esto, cada conexión nueva a ":memory:" ve una base vacía distinta — y el
    TestClient de FastAPI despacha cada request en un hilo del threadpool de
    anyio, así que sin StaticPool los endpoints ven "no such table".
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    db: Session = TestingSession()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def client(session: Session):
    """TestClient cuya app usa la MISMA `session` de este test (no una nueva
    por request): FastAPI's TestClient corre síncrono en un solo hilo, así que
    reusar una sesión es seguro y deja ver, desde el test, los datos creados
    tanto por HTTP como por los helpers de ORM (make_card, make_income, ...).
    """

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def auth_headers(user: "User") -> dict:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def user(session: Session) -> User:
    u = User(email="ana@example.com", password_hash="x")
    session.add(u)
    session.flush()
    return u


@pytest.fixture()
def account(session: Session, user: User) -> Account:
    a = Account(user_id=user.id, name="Débito BBVA", type=AccountType.DEBIT, balance=Decimal("60000.00"))
    session.add(a)
    session.flush()
    return a


@pytest.fixture()
def category(session: Session, user: User) -> Category:
    c = Category(user_id=user.id, name="Comida")
    session.add(c)
    session.flush()
    return c


def make_card(session: Session, user: User, *, statement_day: int, payment_term_days: int, name: str = "Tarjeta") -> CreditCard:
    card = CreditCard(
        user_id=user.id,
        name=name,
        bank="Banco",
        last_four="0000",
        credit_limit=Decimal("20000.00"),
        statement_day=statement_day,
        payment_term_days=payment_term_days,
    )
    session.add(card)
    session.flush()
    return card


def make_cycle(
    session: Session,
    card: CreditCard,
    *,
    start: date,
    end: date,
    due: date,
    status: CycleStatus,
    total_amount: Decimal = Decimal("0"),
    paid_amount: Decimal = Decimal("0"),
) -> BillingCycle:
    cycle = BillingCycle(
        credit_card_id=card.id,
        start_date=start,
        end_date=end,
        due_date=due,
        status=status,
        total_amount=total_amount,
        paid_amount=paid_amount,
    )
    session.add(cycle)
    session.flush()
    return cycle


def make_fixed_expense(
    session: Session,
    user: User,
    category: Category,
    *,
    name: str,
    amount: Decimal,
    day_of_month: int,
    is_active: bool = True,
) -> FixedExpense:
    fixed = FixedExpense(
        user_id=user.id,
        name=name,
        amount=amount,
        day_of_month=day_of_month,
        category_id=category.id,
        is_active=is_active,
    )
    session.add(fixed)
    session.flush()
    return fixed


def make_income(
    session: Session,
    user: User,
    account: Account,
    *,
    amount: Decimal,
    frequency: IncomeFrequency,
    payment_days: List[Union[int, str]],
    is_active: bool = True,
) -> Income:
    income = Income(
        user_id=user.id,
        name="Ingreso",
        amount=amount,
        frequency=frequency,
        payment_days=payment_days,
        account_id=account.id,
        is_active=is_active,
    )
    session.add(income)
    session.flush()
    return income


def make_allocation(
    session: Session, card: CreditCard, cycle: BillingCycle, account: Account, *, amount: Decimal
) -> SavingsAllocation:
    allocation = SavingsAllocation(
        credit_card_id=card.id,
        billing_cycle_id=cycle.id,
        amount=amount,
        source_account_id=account.id,
    )
    session.add(allocation)
    session.flush()
    return allocation


def make_transaction(
    session: Session,
    user: User,
    category: Category,
    *,
    amount: Decimal,
    transaction_date: date,
    cash_flow_date: date,
    payment_method: PaymentMethod = PaymentMethod.CREDIT,
    credit_card_id: Optional[int] = None,
    account_id: Optional[int] = None,
    billing_cycle_id: Optional[int] = None,
) -> Transaction:
    txn = Transaction(
        user_id=user.id,
        amount=amount,
        category_id=category.id,
        transaction_date=transaction_date,
        payment_method=payment_method,
        credit_card_id=credit_card_id,
        account_id=account_id,
        billing_cycle_id=billing_cycle_id,
        cash_flow_date=cash_flow_date,
    )
    session.add(txn)
    session.flush()
    return txn


def make_installment_plan(
    session: Session,
    card: CreditCard,
    transaction: Transaction,
    *,
    description: str,
    total_amount: Decimal,
    months_total: int,
    monthly_amount: Decimal,
    start_date: date,
    months_paid: int = 0,
) -> InstallmentPlan:
    plan = InstallmentPlan(
        credit_card_id=card.id,
        transaction_id=transaction.id,
        description=description,
        total_amount=total_amount,
        months_total=months_total,
        months_paid=months_paid,
        monthly_amount=monthly_amount,
        start_date=start_date,
    )
    session.add(plan)
    session.flush()
    return plan
