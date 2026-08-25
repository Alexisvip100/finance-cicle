from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, User
from app.models.billing_cycle import CycleStatus
from app.models.transaction import PaymentMethod
from app.services import budget_service
from tests.conftest import make_card, make_cycle, make_installment_plan, make_transaction


class TestMonthSummary:
    def test_regla_4_5_msi_cuenta_completo_en_el_mes_de_la_compra(
        self, session: Session, user: User, category: Category
    ):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        txn = make_transaction(
            session, user, category, amount=Decimal("29400.00"),
            transaction_date=date(2026, 8, 26), cash_flow_date=date(2026, 9, 14),
            payment_method=PaymentMethod.CREDIT, credit_card_id=card.id,
        )
        make_installment_plan(
            session, card, txn, description="MacBook Pro", total_amount=Decimal("29400.00"),
            months_total=12, monthly_amount=Decimal("2450.00"), start_date=date(2026, 8, 26), months_paid=4,
        )

        results = budget_service.month_summary(session, user.id, "2026-08")
        assert len(results) == 1
        assert results[0].spent == Decimal("29400.00")
        assert results[0].credit_spent == Decimal("29400.00")
        # 8 mensualidades restantes * 2450 = 19600, no el total ni la mensualidad sola.
        assert results[0].credit_pending == Decimal("19600.00")

        # El mes siguiente no debe repetir el gasto (no hay una segunda Transaction).
        next_month = budget_service.month_summary(session, user.id, "2026-09")
        assert next_month == []

    def test_credit_pendiente_proporcional_a_lo_que_falta_pagar_del_ciclo(
        self, session: Session, user: User, category: Category
    ):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 14),
            status=CycleStatus.PARTIALLY_PAID, total_amount=Decimal("2000.00"), paid_amount=Decimal("1000.00"),
        )
        make_transaction(
            session, user, category, amount=Decimal("2000.00"),
            transaction_date=date(2026, 8, 15), cash_flow_date=date(2026, 9, 14),
            payment_method=PaymentMethod.CREDIT, credit_card_id=card.id, billing_cycle_id=cycle.id,
        )

        results = budget_service.month_summary(session, user.id, "2026-08")
        assert results[0].spent == Decimal("2000.00")
        assert results[0].credit_pending == Decimal("1000.00")  # 50% del ciclo sigue sin pagarse

    def test_credit_pagado_por_completo_no_esta_pendiente(
        self, session: Session, user: User, category: Category
    ):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 14),
            status=CycleStatus.PAID, total_amount=Decimal("2000.00"), paid_amount=Decimal("2000.00"),
        )
        make_transaction(
            session, user, category, amount=Decimal("2000.00"),
            transaction_date=date(2026, 8, 15), cash_flow_date=date(2026, 9, 14),
            payment_method=PaymentMethod.CREDIT, credit_card_id=card.id, billing_cycle_id=cycle.id,
        )
        results = budget_service.month_summary(session, user.id, "2026-08")
        assert results[0].credit_pending == Decimal("0")

    def test_gasto_en_efectivo_no_genera_credit_pending(
        self, session: Session, user: User, account, category: Category
    ):
        make_transaction(
            session, user, category, amount=Decimal("500.00"),
            transaction_date=date(2026, 8, 5), cash_flow_date=date(2026, 8, 5),
            payment_method=PaymentMethod.CASH, account_id=account.id,
        )
        results = budget_service.month_summary(session, user.id, "2026-08")
        assert results[0].spent == Decimal("500.00")
        assert results[0].credit_spent == Decimal("0")
        assert results[0].credit_pending == Decimal("0")

    def test_categoria_sin_gasto_ni_limite_no_aparece(self, session: Session, user: User, category: Category):
        results = budget_service.month_summary(session, user.id, "2026-08")
        assert results == []

    def test_categoria_con_limite_pero_sin_gasto_si_aparece(self, session: Session, user: User):
        category = Category(user_id=user.id, name="Entretenimiento", monthly_limit=Decimal("1500.00"))
        session.add(category)
        session.flush()

        results = budget_service.month_summary(session, user.id, "2026-08")
        assert len(results) == 1
        assert results[0].spent == Decimal("0")
        assert results[0].monthly_limit == Decimal("1500.00")
