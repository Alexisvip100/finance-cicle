from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountType, Category, User
from app.models.billing_cycle import CycleStatus
from app.models.income import IncomeFrequency
from app.services import balance_service
from tests.conftest import make_allocation, make_card, make_cycle, make_fixed_expense, make_income


class TestCalculateCommitted:
    def test_suma_closed_y_partially_paid_y_excluye_open_y_paid(self, session: Session, user: User):
        card = make_card(session, user, statement_day=25, payment_term_days=20)

        make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"), paid_amount=Decimal("0"),
        )
        make_cycle(
            session, card, start=date(2026, 6, 12), end=date(2026, 7, 12), due=date(2026, 8, 7),
            status=CycleStatus.PARTIALLY_PAID, total_amount=Decimal("8450.00"), paid_amount=Decimal("3450.00"),
        )
        # Estos dos NO deben contar:
        make_cycle(
            session, card, start=date(2026, 8, 25), end=date(2026, 9, 25), due=date(2026, 10, 15),
            status=CycleStatus.OPEN, total_amount=Decimal("4320.50"),
        )
        make_cycle(
            session, card, start=date(2026, 5, 25), end=date(2026, 6, 25), due=date(2026, 7, 15),
            status=CycleStatus.PAID, total_amount=Decimal("1000.00"), paid_amount=Decimal("1000.00"),
        )

        committed = balance_service.calculate_committed(session, user.id)
        # 12000 (closed, nada pagado) + (8450 - 3450) parcial = 17000
        assert committed == Decimal("17000.00")


class TestCalculatePendingFixed:
    def test_solo_cuenta_lo_que_cae_entre_hoy_y_el_proximo_ingreso(
        self, session: Session, user: User, category: Category
    ):
        make_fixed_expense(session, user, category, name="Renta", amount=Decimal("18500.00"), day_of_month=1)
        make_fixed_expense(session, user, category, name="Spotify", amount=Decimal("129.00"), day_of_month=16)
        make_fixed_expense(session, user, category, name="Netflix", amount=Decimal("299.00"), day_of_month=22)

        # Hoy 4 sep, próximo ingreso 15 sep: solo cae en la ventana [4, 15) nada
        # de esta lista (Renta ya pasó el día 1, Spotify/Netflix son después del 15).
        pending = balance_service.calculate_pending_fixed(
            session, user.id, as_of=date(2026, 9, 4), until=date(2026, 9, 15)
        )
        assert pending == Decimal("0.00")

        # Si el próximo ingreso fuera hasta el 25, Spotify (16) y Netflix (22) sí entran.
        pending_wider = balance_service.calculate_pending_fixed(
            session, user.id, as_of=date(2026, 9, 4), until=date(2026, 9, 25)
        )
        assert pending_wider == Decimal("428.00")

    def test_sin_proximo_ingreso_resoluble_regresa_cero_explicito(
        self, session: Session, user: User, category: Category
    ):
        make_fixed_expense(session, user, category, name="Renta", amount=Decimal("18500.00"), day_of_month=1)
        pending = balance_service.calculate_pending_fixed(session, user.id, as_of=date(2026, 9, 4), until=None)
        assert pending == Decimal("0.00")

    def test_ignora_fixed_expenses_inactivos(self, session: Session, user: User, category: Category):
        make_fixed_expense(
            session, user, category, name="Gym (cancelado)", amount=Decimal("500.00"), day_of_month=10,
            is_active=False,
        )
        pending = balance_service.calculate_pending_fixed(
            session, user.id, as_of=date(2026, 9, 4), until=date(2026, 9, 20)
        )
        assert pending == Decimal("0.00")


class TestCalculateAvailable:
    def test_formula_completa_sin_apartados(
        self, session: Session, user: User, category: Category, account: Account
    ):
        # `account` (fixture) ya crea "Débito BBVA" con 60000.00
        cash_account = Account(user_id=user.id, name="Efectivo", type=AccountType.CASH, balance=Decimal("2500.00"))
        session.add(cash_account)
        session.flush()

        card = make_card(session, user, statement_day=25, payment_term_days=20, name="Amex Platino")
        make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )
        card_b = make_card(session, user, statement_day=12, payment_term_days=26, name="Tarjeta Nu")
        make_cycle(
            session, card_b, start=date(2026, 7, 12), end=date(2026, 8, 12), due=date(2026, 9, 7),
            status=CycleStatus.CLOSED, total_amount=Decimal("8450.00"),
        )

        make_income(
            session, user, account, amount=Decimal("15000.00"),
            frequency=IncomeFrequency.BIWEEKLY, payment_days=[15, "LAST_DAY"],
        )
        make_fixed_expense(session, user, category, name="Spotify", amount=Decimal("129.00"), day_of_month=16)

        result = balance_service.calculate_available(session, user.id, as_of=date(2026, 9, 4))

        assert result.accounts_total == Decimal("62500.00")  # 2500 + 60000
        assert result.committed == Decimal("20450.00")  # 12000 + 8450
        assert result.next_income_date == date(2026, 9, 15)
        assert result.pending_fixed == Decimal("0.00")  # Spotify (16) cae después del ingreso (15)
        assert result.available == Decimal("42050.00")  # 62500 - 20450 - 0

    def test_apartado_no_se_resta_dos_veces(self, session: Session, user: User, account: Account):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2026, 7, 25), end=date(2026, 8, 25), due=date(2026, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        before = balance_service.calculate_available(session, user.id, as_of=date(2026, 9, 4))

        # Apartar dinero para este ciclo no debe cambiar el disponible real:
        # ya está contado dentro de accounts_total y dentro de committed.
        make_allocation(session, card, cycle, account, amount=Decimal("8500.00"))

        after = balance_service.calculate_available(session, user.id, as_of=date(2026, 9, 4))
        assert after.available == before.available
        assert after.committed == before.committed
        assert after.accounts_total == before.accounts_total

    def test_ciclo_abierto_no_se_resta(self, session: Session, user: User, account: Account):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        make_cycle(
            session, card, start=date(2026, 8, 25), end=date(2026, 9, 25), due=date(2026, 10, 15),
            status=CycleStatus.OPEN, total_amount=Decimal("4320.50"),
        )

        result = balance_service.calculate_available(session, user.id, as_of=date(2026, 9, 4))
        assert result.committed == Decimal("0.00")
        assert result.available == account.balance
