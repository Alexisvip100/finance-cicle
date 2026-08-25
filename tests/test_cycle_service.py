from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, CreditCard, PaymentMethod, Transaction, User
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.services import cycle_service
from tests.conftest import make_card

# ---------------------------------------------------------------------------
# Funciones puras (sin DB): resolve_statement_date / resolve_cycle_bounds.
# Si estas fallan, todo lo demás falla — por eso van primero y sin infraestructura.
# ---------------------------------------------------------------------------


class TestResolveStatementDate:
    def test_normal_day_within_month(self):
        assert cycle_service.resolve_statement_date(2026, 8, 25) == date(2026, 8, 25)

    def test_caso_2_dia_31_en_febrero_no_bisiesto(self):
        # 2026 no es bisiesto (no divisible entre 4) → febrero tiene 28 días.
        assert cycle_service.resolve_statement_date(2026, 2, 31) == date(2026, 2, 28)

    def test_dia_31_en_febrero_bisiesto(self):
        # 2024 sí es bisiesto → febrero tiene 29 días.
        assert cycle_service.resolve_statement_date(2024, 2, 31) == date(2024, 2, 29)

    def test_dia_31_en_mes_de_30_dias(self):
        assert cycle_service.resolve_statement_date(2026, 9, 31) == date(2026, 9, 30)


class TestResolveCycleBounds:
    def test_caso_1_compra_el_dia_exacto_del_corte_cae_en_el_ciclo_que_abre(self):
        bounds = cycle_service.resolve_cycle_bounds(
            statement_day=25, payment_term_days=20, reference_date=date(2026, 8, 25)
        )
        assert bounds.start == date(2026, 8, 25)
        assert bounds.end == date(2026, 9, 25)
        assert bounds.due == date(2026, 10, 15)  # 25 sep + 20 días

    def test_compra_un_dia_antes_del_corte_cae_en_el_ciclo_que_cierra(self):
        bounds = cycle_service.resolve_cycle_bounds(
            statement_day=25, payment_term_days=20, reference_date=date(2026, 8, 24)
        )
        assert bounds.start == date(2026, 7, 25)
        assert bounds.end == date(2026, 8, 25)
        assert bounds.due == date(2026, 9, 14)  # 25 ago + 20 días

    def test_ejemplo_del_spec_amex_platino(self):
        # corte 25, plazo 20: comprar hoy (dentro del ciclo abierto 25 ago-25 sep)
        # se paga el 15 oct (25 sep + 20). Coincide con la pantalla de "Nueva Tarjeta".
        bounds = cycle_service.resolve_cycle_bounds(
            statement_day=25, payment_term_days=20, reference_date=date(2026, 9, 4)
        )
        assert bounds.start == date(2026, 8, 25)
        assert bounds.end == date(2026, 9, 25)
        assert bounds.due == date(2026, 10, 15)

    def test_ejemplo_del_spec_tarjeta_nu(self):
        # corte 12, plazo lo suficiente para vencer el día 7 del mes siguiente al cierre.
        # ciclo abierto 12 ago - 12 sep, cierre 12 sep + 26 días = 8 oct... usamos el
        # ejemplo real de la spec: ciclo cerrado 12 jul-12 ago vence 7 sep => plazo=26.
        bounds = cycle_service.resolve_cycle_bounds(
            statement_day=12, payment_term_days=26, reference_date=date(2026, 8, 1)
        )
        assert bounds.start == date(2026, 7, 12)
        assert bounds.end == date(2026, 8, 12)
        assert bounds.due == date(2026, 9, 7)

    def test_corte_31_en_mes_de_30_dias_no_rompe_el_rango(self):
        bounds = cycle_service.resolve_cycle_bounds(
            statement_day=31, payment_term_days=15, reference_date=date(2026, 9, 15)
        )
        # Septiembre no tiene 31: el corte de septiembre se resuelve al 30.
        assert bounds.start == date(2026, 8, 31)
        assert bounds.end == date(2026, 9, 30)


# ---------------------------------------------------------------------------
# Funciones con DB: get_or_create_cycle / generate_cycles / close_due_cycles /
# regenerate_future_cycles / recalculate_cycle_total.
# ---------------------------------------------------------------------------


class TestGetOrCreateCycle:
    def test_es_idempotente(self, session: Session, user: User):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        first = cycle_service.get_or_create_cycle(session, card, date(2026, 8, 25))
        second = cycle_service.get_or_create_cycle(session, card, date(2026, 9, 10))
        assert first.id == second.id  # ambas fechas caen en el mismo ciclo abierto

    def test_caso_10_dos_tarjetas_con_cortes_distintos_no_se_mezclan(self, session: Session, user: User):
        card_a = make_card(session, user, statement_day=25, payment_term_days=20, name="Amex Platino")
        card_b = make_card(session, user, statement_day=12, payment_term_days=26, name="Tarjeta Nu")

        cycle_a = cycle_service.get_or_create_cycle(session, card_a, date(2026, 8, 20))
        cycle_b = cycle_service.get_or_create_cycle(session, card_b, date(2026, 8, 20))

        assert cycle_a.credit_card_id == card_a.id
        assert cycle_b.credit_card_id == card_b.id
        assert cycle_a.start_date == date(2026, 7, 25)
        assert cycle_a.end_date == date(2026, 8, 25)
        assert cycle_b.start_date == date(2026, 8, 12)
        assert cycle_b.end_date == date(2026, 9, 12)


class TestRecalculateCycleTotal:
    def test_suma_las_transacciones_del_ciclo_y_se_recalcula_al_borrar_una(
        self, session: Session, user: User, category: Category
    ):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = cycle_service.get_or_create_cycle(session, card, date(2026, 8, 25))

        t1 = Transaction(
            user_id=user.id,
            amount=Decimal("600.00"),
            category_id=category.id,
            transaction_date=date(2026, 8, 26),
            payment_method=PaymentMethod.CREDIT,
            credit_card_id=card.id,
            billing_cycle_id=cycle.id,
            cash_flow_date=cycle.due_date,
        )
        t2 = Transaction(
            user_id=user.id,
            amount=Decimal("840.50"),
            category_id=category.id,
            transaction_date=date(2026, 8, 27),
            payment_method=PaymentMethod.CREDIT,
            credit_card_id=card.id,
            billing_cycle_id=cycle.id,
            cash_flow_date=cycle.due_date,
        )
        session.add_all([t1, t2])
        session.flush()

        cycle_service.recalculate_cycle_total(session, cycle)
        assert cycle.total_amount == Decimal("1440.50")

        # Caso de prueba #11: eliminar una transacción de un ciclo ya cerrado
        # (aquí simulamos "ya cerrado" con el mismo cálculo, que es agnóstico
        # del status) recalcula el monto del ciclo.
        session.delete(t1)
        session.flush()
        cycle_service.recalculate_cycle_total(session, cycle)
        assert cycle.total_amount == Decimal("840.50")


class TestGenerateCycles:
    def test_crea_el_ciclo_actual_y_los_siguientes_sin_duplicar(self, session: Session, user: User):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        today = date(2026, 8, 24)
        created_first = cycle_service.generate_cycles(session, card, months_ahead=3, today=today)
        assert len(created_first) == 4  # actual + 3 hacia adelante

        created_second = cycle_service.generate_cycles(session, card, months_ahead=3, today=today)
        assert created_second == []  # ya existían, no duplica

        total_cycles = session.query(BillingCycle).filter_by(credit_card_id=card.id).count()
        assert total_cycles == 4


class TestCloseDueCycles:
    def test_cierra_ciclos_vencidos_y_fija_el_total(self, session: Session, user: User, category: Category):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = cycle_service.get_or_create_cycle(session, card, date(2026, 6, 1))
        assert cycle.end_date == date(2026, 6, 25)

        transaction = Transaction(
            user_id=user.id,
            amount=Decimal("2000.00"),
            category_id=category.id,
            transaction_date=date(2026, 6, 10),
            payment_method=PaymentMethod.CREDIT,
            credit_card_id=card.id,
            billing_cycle_id=cycle.id,
            cash_flow_date=cycle.due_date,
        )
        session.add(transaction)
        session.flush()

        closed = cycle_service.close_due_cycles(session, today=date(2026, 8, 1))
        assert len(closed) == 1
        assert closed[0].id == cycle.id
        assert closed[0].status == CycleStatus.CLOSED
        assert closed[0].total_amount == Decimal("2000.00")

    def test_no_cierra_ciclos_todavia_abiertos(self, session: Session, user: User):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle_service.get_or_create_cycle(session, card, date(2026, 9, 1))

        closed = cycle_service.close_due_cycles(session, today=date(2026, 8, 1))
        assert closed == []


class TestRegenerateFutureCycles:
    def test_caso_12_no_toca_ciclos_cerrados_pero_regenera_los_abiertos(
        self, session: Session, user: User
    ):
        card = make_card(session, user, statement_day=25, payment_term_days=20)

        # Ciclo histórico ya cerrado: no debe cambiar aunque cambie la config de la tarjeta.
        closed_cycle = cycle_service.get_or_create_cycle(session, card, date(2026, 5, 1))
        closed_cycle.status = CycleStatus.CLOSED
        session.flush()
        closed_cycle_id = closed_cycle.id
        closed_start = closed_cycle.start_date
        closed_end = closed_cycle.end_date

        # Ciclos abiertos generados con la configuración vieja (corte 25).
        today = date(2026, 8, 24)
        cycle_service.generate_cycles(session, card, months_ahead=2, today=today)
        open_cycles_before = (
            session.query(BillingCycle)
            .filter_by(credit_card_id=card.id, status=CycleStatus.OPEN)
            .all()
        )
        assert len(open_cycles_before) > 0
        assert all(c.start_date.day == 25 for c in open_cycles_before)

        # Cambia la config de la tarjeta y regenera.
        card.statement_day = 10
        session.flush()
        cycle_service.regenerate_future_cycles(session, card, months_ahead=2, today=today)

        # El ciclo cerrado sigue intacto.
        untouched = session.get(BillingCycle, closed_cycle_id)
        assert untouched is not None
        assert untouched.status == CycleStatus.CLOSED
        assert untouched.start_date == closed_start
        assert untouched.end_date == closed_end

        # Los ciclos abiertos ahora reflejan el nuevo día de corte.
        open_cycles_after = (
            session.query(BillingCycle)
            .filter_by(credit_card_id=card.id, status=CycleStatus.OPEN)
            .all()
        )
        assert len(open_cycles_after) > 0
        assert all(c.start_date.day == 10 for c in open_cycles_after)
