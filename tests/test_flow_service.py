from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, Category, User
from app.models.billing_cycle import CycleStatus
from app.models.income import IncomeFrequency
from app.services import flow_service
from tests.conftest import (
    make_card,
    make_cycle,
    make_fixed_expense,
    make_income,
    make_installment_plan,
    make_transaction,
)


class TestProjectEvents:
    def test_solo_incluye_pagos_reales_no_el_corte_de_un_ciclo_abierto(
        self, session: Session, user: User, account: Account
    ):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        # Cerrado y no pagado: SÍ debe aparecer, en su vencimiento (14 sep), no en el corte (25 ago).
        make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )
        # Abierto: NO debe generar un pago; solo un hito sin monto en su corte (25 sep).
        make_cycle(
            session, card, start=date(2026, 8, 25), end=date(2026, 9, 25), due=date(2026, 10, 15),
            status=CycleStatus.OPEN, total_amount=Decimal("4320.50"),
        )

        result = flow_service.project(session, user.id, days=60, as_of=date(2026, 9, 4))

        card_due_events = [e for e in result.events if e.kind == "card_due"]
        milestone_events = [e for e in result.events if e.kind == "cycle_open_milestone"]

        assert len(card_due_events) == 1
        assert card_due_events[0].date == date(2026, 9, 14)
        assert card_due_events[0].amount == Decimal("-12000.00")

        assert len(milestone_events) == 1
        assert milestone_events[0].date == date(2026, 9, 25)
        assert milestone_events[0].amount is None

    def test_ciclo_pagado_no_genera_evento(self, session: Session, user: User, account: Account):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 14),
            status=CycleStatus.PAID, total_amount=Decimal("12000.00"), paid_amount=Decimal("12000.00"),
        )
        result = flow_service.project(session, user.id, days=60, as_of=date(2026, 9, 4))
        assert result.events == []

    def test_incluye_ingresos_futuros_dentro_de_la_ventana(
        self, session: Session, user: User, account: Account
    ):
        make_income(
            session, user, account, amount=Decimal("15000.00"),
            frequency=IncomeFrequency.BIWEEKLY, payment_days=[15, "LAST_DAY"],
        )
        result = flow_service.project(session, user.id, days=30, as_of=date(2026, 9, 4))
        income_events = [e for e in result.events if e.kind == "income"]
        assert [e.date for e in income_events] == [date(2026, 9, 15), date(2026, 9, 30)]
        assert all(e.amount == Decimal("15000.00") for e in income_events)

    def test_incluye_gastos_fijos_dentro_de_la_ventana(
        self, session: Session, user: User, account: Account, category: Category
    ):
        make_fixed_expense(session, user, category, name="Spotify", amount=Decimal("129.00"), day_of_month=16)
        result = flow_service.project(session, user.id, days=30, as_of=date(2026, 9, 4))
        fixed_events = [e for e in result.events if e.kind == "fixed_expense"]
        assert len(fixed_events) == 1
        assert fixed_events[0].date == date(2026, 9, 16)
        assert fixed_events[0].amount == Decimal("-129.00")

    def test_msi_solo_proyecta_las_mensualidades_restantes(
        self, session: Session, user: User, account: Account, category: Category
    ):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        original_txn = make_transaction(
            session, user, category, amount=Decimal("29400.00"),
            transaction_date=date(2026, 5, 25), cash_flow_date=date(2026, 6, 14),
            credit_card_id=card.id,
        )
        # MacBook Pro: 12 meses, ya van 4 pagados (regla 4.5: se proyectan solo las 8 restantes).
        make_installment_plan(
            session, card, original_txn,
            description="MacBook Pro", total_amount=Decimal("29400.00"),
            months_total=12, monthly_amount=Decimal("2450.00"),
            start_date=date(2026, 5, 25), months_paid=4,
        )

        result = flow_service.project(session, user.id, days=90, as_of=date(2026, 9, 4))
        installment_events = [e for e in result.events if e.kind == "installment"]

        # Ciclos desde 25 may: (25may-25jun,due14jul)=#1 ... la 5a mensualidad
        # (índice 4, la primera no pagada) vence el mismo patrón +1 ciclo cada vez.
        # Solo nos importa: son las restantes (12-4=8) y ninguna es anterior a hoy
        # salvo las que ya caigan fuera de la ventana de 90 días.
        assert len(installment_events) <= 8
        assert all(e.amount == Decimal("-2450.00") for e in installment_events)
        assert all(e.date >= date(2026, 9, 4) for e in installment_events)


class TestDeficitRisk:
    def test_caso_9_marca_deficit_risk_con_la_fecha_del_cruce(
        self, session: Session, user: User, account: Account
    ):
        # Cuenta con poco saldo (fixture `account` = 60000) — forzamos un déficit
        # bajando el saldo y metiendo un pago de tarjeta grande.
        account.balance = Decimal("5000.00")
        session.flush()

        card = make_card(session, user, statement_day=25, payment_term_days=20)
        make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 20),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        result = flow_service.project(session, user.id, days=60, as_of=date(2026, 9, 4))

        assert result.deficit_risk is True
        assert result.deficit_date == date(2026, 9, 20)
        assert result.ending_balance == Decimal("-7000.00")  # 5000 - 12000

    def test_sin_eventos_suficientes_no_hay_riesgo_de_deficit(
        self, session: Session, user: User, account: Account
    ):
        result = flow_service.project(session, user.id, days=30, as_of=date(2026, 9, 4))
        assert result.deficit_risk is False
        assert result.deficit_date is None
        assert result.ending_balance == account.balance

    def test_un_ingreso_despues_del_deficit_no_lo_cancela_retroactivamente(
        self, session: Session, user: User, account: Account
    ):
        account.balance = Decimal("5000.00")
        session.flush()
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 10),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )
        make_income(
            session, user, account, amount=Decimal("15000.00"),
            frequency=IncomeFrequency.MONTHLY, payment_days=[15],
        )

        result = flow_service.project(session, user.id, days=30, as_of=date(2026, 9, 4))

        # El déficit ocurrió el 10 (5000-12000=-7000) aunque el 15 llegue el
        # ingreso y el saldo termine positivo (-7000+15000=8000).
        assert result.deficit_risk is True
        assert result.deficit_date == date(2026, 9, 10)
        assert result.ending_balance == Decimal("8000.00")


class TestGroupEventsByWeek:
    def test_agrupa_en_buckets_de_7_dias(self, session: Session, user: User, account: Account, category: Category):
        make_fixed_expense(session, user, category, name="Renta", amount=Decimal("18500.00"), day_of_month=1)
        make_fixed_expense(session, user, category, name="Spotify", amount=Decimal("129.00"), day_of_month=16)

        result = flow_service.project(session, user.id, days=30, as_of=date(2026, 9, 4))
        grouped = flow_service.group_events_by_week(result.events, as_of=date(2026, 9, 4), days=30)

        # 30 días -> semanas 0..4 (ceil(30/7)=5), todas presentes aunque estén vacías.
        assert [b["week_index"] for b in grouped] == [0, 1, 2, 3, 4]

        # Renta (día1) ya pasó (antes de hoy=4), no debería aparecer en absoluto.
        all_dates = [e.date for bucket in grouped for e in bucket["events"]]
        assert date(2026, 9, 1) not in all_dates

        # Spotify el 16 sep cae en la semana índice (16-4)//7 = 1 ("próxima semana").
        spotify_bucket = next(b for b in grouped if any(e.label == "Spotify" for e in b["events"]))
        assert spotify_bucket["week_index"] == 1

        # Semana 0 no tiene eventos (Renta ya pasó) pero sigue apareciendo, vacía.
        week_zero = next(b for b in grouped if b["week_index"] == 0)
        assert week_zero["events"] == []
