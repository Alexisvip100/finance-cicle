from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, User
from app.models.billing_cycle import BillingCycle, CycleStatus
from app.models.savings_allocation import SavingsAllocation
from app.services import balance_service
from tests.conftest import auth_headers, make_card, make_cycle


def _create_account(client, user, balance="60000.00"):
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Débito BBVA", "type": "DEBIT", "balance": balance},
        headers=auth_headers(user),
    )
    return response.json()["id"]


class TestAllocations:
    def test_apartar_no_mueve_dinero_real(self, client, session: Session, user: User):
        account_id = _create_account(client, user, balance="60000.00")
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        response = client.post(
            f"/api/v1/cards/{card.id}/allocations",
            json={"billing_cycle_id": cycle.id, "amount": "8500.00", "source_account_id": account_id},
            headers=auth_headers(user),
        )
        assert response.status_code == 201

        account = session.get(Account, account_id)
        assert account.balance == Decimal("60000.00")  # sin cambio: apartar no mueve dinero

    def test_caso_7_apartar_mas_que_el_ciclo_se_permite(self, client, session: Session, user: User):
        account_id = _create_account(client, user)
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("1000.00"),
        )
        response = client.post(
            f"/api/v1/cards/{card.id}/allocations",
            json={"billing_cycle_id": cycle.id, "amount": "5000.00", "source_account_id": account_id},
            headers=auth_headers(user),
        )
        assert response.status_code == 201  # no se rechaza

    def test_retirar_apartado_no_mueve_dinero(self, client, session: Session, user: User):
        account_id = _create_account(client, user, balance="60000.00")
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )
        create = client.post(
            f"/api/v1/cards/{card.id}/allocations",
            json={"billing_cycle_id": cycle.id, "amount": "8500.00", "source_account_id": account_id},
            headers=auth_headers(user),
        )
        allocation_id = create.json()["id"]

        response = client.delete(f"/api/v1/allocations/{allocation_id}", headers=auth_headers(user))
        assert response.status_code == 204
        account = session.get(Account, account_id)
        assert account.balance == Decimal("60000.00")


class TestPayments:
    def test_pago_total_desde_cuenta(self, client, session: Session, user: User):
        account_id = _create_account(client, user, balance="20000.00")
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        response = client.post(
            f"/api/v1/cards/{card.id}/payments",
            json={
                "billing_cycle_id": cycle.id, "amount": "12000.00",
                "source_type": "ACCOUNT", "source_account_id": account_id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201

        session.expire_all()
        assert session.get(Account, account_id).balance == Decimal("8000.00")
        updated_cycle = session.get(BillingCycle, cycle.id)
        assert updated_cycle.status == CycleStatus.PAID
        assert updated_cycle.paid_amount == Decimal("12000.00")

    def test_caso_6_pago_parcial_deja_partially_paid_y_resto_comprometido(
        self, client, session: Session, user: User
    ):
        account_id = _create_account(client, user, balance="20000.00")
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        client.post(
            f"/api/v1/cards/{card.id}/payments",
            json={
                "billing_cycle_id": cycle.id, "amount": "5000.00",
                "source_type": "ACCOUNT", "source_account_id": account_id,
            },
            headers=auth_headers(user),
        )
        session.expire_all()
        updated_cycle = session.get(BillingCycle, cycle.id)
        assert updated_cycle.status == CycleStatus.PARTIALLY_PAID

        committed = balance_service.calculate_committed(session, user.id)
        assert committed == Decimal("7000.00")  # 12000 - 5000 sigue comprometido

    def test_no_se_puede_pagar_un_ciclo_abierto(self, client, session: Session, user: User):
        account_id = _create_account(client, user)
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.OPEN, total_amount=Decimal("500.00"),
        )
        response = client.post(
            f"/api/v1/cards/{card.id}/payments",
            json={
                "billing_cycle_id": cycle.id, "amount": "500.00",
                "source_type": "ACCOUNT", "source_account_id": account_id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 400

    def test_no_se_puede_pagar_mas_de_lo_pendiente(self, client, session: Session, user: User):
        account_id = _create_account(client, user, balance="99999.00")
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("1000.00"),
        )
        response = client.post(
            f"/api/v1/cards/{card.id}/payments",
            json={
                "billing_cycle_id": cycle.id, "amount": "1000.01",
                "source_type": "ACCOUNT", "source_account_id": account_id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 400

    def test_caso_6_pago_desde_apartado_no_cambia_disponible_real(
        self, client, session: Session, user: User
    ):
        account_id = _create_account(client, user, balance="20000.00")
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        cycle = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )
        client.post(
            f"/api/v1/cards/{card.id}/allocations",
            json={"billing_cycle_id": cycle.id, "amount": "8500.00", "source_account_id": account_id},
            headers=auth_headers(user),
        )

        before = balance_service.calculate_available(session, user.id, as_of=date(2000, 9, 1))

        response = client.post(
            f"/api/v1/cards/{card.id}/payments",
            json={"billing_cycle_id": cycle.id, "amount": "8500.00", "source_type": "ALLOCATION"},
            headers=auth_headers(user),
        )
        assert response.status_code == 201

        session.expire_all()
        after = balance_service.calculate_available(session, user.id, as_of=date(2000, 9, 1))
        assert after.available == before.available  # regla 4.6/4.2

        # La allocation se consumió por completo.
        remaining_allocations = (
            session.query(SavingsAllocation).filter_by(billing_cycle_id=cycle.id).count()
        )
        assert remaining_allocations == 0

        account = session.get(Account, account_id)
        assert account.balance == Decimal("11500.00")  # 20000 - 8500, el dinero sí sale de verdad
