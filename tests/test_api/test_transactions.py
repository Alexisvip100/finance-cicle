from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountType, Category, User
from app.models.billing_cycle import BillingCycle
from app.models.transaction import Transaction
from tests.conftest import auth_headers


def _create_card(client, user):
    response = client.post(
        "/api/v1/cards",
        json={
            "name": "Amex Platino", "bank": "Amex", "last_four": "4092",
            "credit_limit": "45000.00", "statement_day": 25, "payment_term_days": 20,
        },
        headers=auth_headers(user),
    )
    return response.json()["id"]


def _create_account(client, user, balance="60000.00"):
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Débito BBVA", "type": "DEBIT", "balance": balance},
        headers=auth_headers(user),
    )
    return response.json()["id"]


class TestCreateTransaction:
    def test_gasto_en_efectivo_decrementa_la_cuenta(
        self, client, session: Session, user: User, category: Category
    ):
        account_id = _create_account(client, user, balance="2500.00")

        response = client.post(
            "/api/v1/transactions",
            json={
                "amount": "600.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-09-04",
                "payment_method": "CASH", "account_id": account_id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["cash_flow_date"] == "2026-09-04"
        assert body["billing_cycle_id"] is None

        account = session.get(Account, account_id)
        assert account.balance == Decimal("1900.00")

    def test_gasto_con_tarjeta_resuelve_ciclo_y_actualiza_su_total(
        self, client, session: Session, user: User, category: Category
    ):
        card_id = _create_card(client, user)

        response = client.post(
            "/api/v1/transactions",
            json={
                "amount": "2000.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-08-26",
                "payment_method": "CREDIT", "credit_card_id": card_id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["billing_cycle_id"] is not None
        # 26 ago cae en el ciclo 25ago-25sep (statement_day=25), vence 15 oct.
        assert body["cash_flow_date"] == "2026-10-15"

        cycle = session.get(BillingCycle, body["billing_cycle_id"])
        assert cycle.total_amount == Decimal("2000.00")

    def test_msi_no_crea_transacciones_extra_y_devenga_completo_hoy(
        self, client, session: Session, user: User, category: Category
    ):
        card_id = _create_card(client, user)

        response = client.post(
            "/api/v1/transactions",
            json={
                "amount": "29400.00", "category_id": category.id, "description": "MacBook Pro", "transaction_date": "2026-08-26",
                "payment_method": "CREDIT", "credit_card_id": card_id, "installment_months": 12,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["billing_cycle_id"] is None  # el devengado no cuenta hacia comprometido de un solo ciclo

        from app.models.installment_plan import InstallmentPlan

        plan = session.query(InstallmentPlan).filter_by(transaction_id=body["id"]).one()
        assert plan.months_total == 12

        # Solo esta transacción existe (no 12).
        count = session.query(Transaction).filter_by(user_id=user.id).count()
        assert count == 1

    def test_categoria_es_opcional_pero_description_es_obligatoria(
        self, client, session: Session, user: User
    ):
        account_id = _create_account(client, user, balance="2500.00")

        sin_descripcion = client.post(
            "/api/v1/transactions",
            json={"amount": "100.00", "transaction_date": "2026-09-04", "payment_method": "CASH", "account_id": account_id},
            headers=auth_headers(user),
        )
        assert sin_descripcion.status_code == 422  # description es obligatoria

        response = client.post(
            "/api/v1/transactions",
            json={
                "amount": "100.00", "description": "Café", "transaction_date": "2026-09-04",
                "payment_method": "CASH", "account_id": account_id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        assert response.json()["category_id"] is None
        assert response.json()["description"] == "Café"

    def test_credit_sin_credit_card_id_es_invalido(self, client, user: User, category: Category):
        response = client.post(
            "/api/v1/transactions",
            json={"amount": "100.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-09-04", "payment_method": "CREDIT"},
            headers=auth_headers(user),
        )
        assert response.status_code == 422

    def test_msi_en_efectivo_es_invalido(self, client, user: User, category: Category):
        account_id = _create_account(client, user)
        response = client.post(
            "/api/v1/transactions",
            json={
                "amount": "100.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-09-04",
                "payment_method": "CASH", "account_id": account_id, "installment_months": 3,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 422


class TestListTransactions:
    def test_filtra_por_categoria_y_fecha(self, client, user: User, category: Category):
        account_id = _create_account(client, user)
        client.post(
            "/api/v1/transactions",
            json={
                "amount": "100.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-09-04",
                "payment_method": "CASH", "account_id": account_id,
            },
            headers=auth_headers(user),
        )
        client.post(
            "/api/v1/transactions",
            json={
                "amount": "200.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-01-01",
                "payment_method": "CASH", "account_id": account_id,
            },
            headers=auth_headers(user),
        )
        response = client.get(
            "/api/v1/transactions", params={"from_date": "2026-09-01"}, headers=auth_headers(user)
        )
        assert len(response.json()) == 1
        assert response.json()[0]["amount"] == "100.00"


class TestDeleteTransaction:
    def test_borrar_gasto_en_efectivo_regresa_el_dinero_a_la_cuenta(
        self, client, session: Session, user: User, category: Category
    ):
        account_id = _create_account(client, user, balance="2500.00")
        create = client.post(
            "/api/v1/transactions",
            json={
                "amount": "600.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-09-04",
                "payment_method": "CASH", "account_id": account_id,
            },
            headers=auth_headers(user),
        )
        txn_id = create.json()["id"]

        response = client.delete(f"/api/v1/transactions/{txn_id}", headers=auth_headers(user))
        assert response.status_code == 204

        account = session.get(Account, account_id)
        assert account.balance == Decimal("2500.00")

    def test_caso_11_borrar_de_un_ciclo_recalcula_su_total(
        self, client, session: Session, user: User, category: Category
    ):
        card_id = _create_card(client, user)
        r1 = client.post(
            "/api/v1/transactions",
            json={
                "amount": "2000.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-08-26",
                "payment_method": "CREDIT", "credit_card_id": card_id,
            },
            headers=auth_headers(user),
        )
        r2 = client.post(
            "/api/v1/transactions",
            json={
                "amount": "500.00", "category_id": category.id, "description": "Compra de prueba", "transaction_date": "2026-08-27",
                "payment_method": "CREDIT", "credit_card_id": card_id,
            },
            headers=auth_headers(user),
        )
        cycle_id = r1.json()["billing_cycle_id"]
        assert session.get(BillingCycle, cycle_id).total_amount == Decimal("2500.00")

        client.delete(f"/api/v1/transactions/{r1.json()['id']}", headers=auth_headers(user))

        session.expire_all()
        assert session.get(BillingCycle, cycle_id).total_amount == Decimal("500.00")

    def test_no_se_puede_registrar_un_gasto_en_un_ciclo_ya_cerrado(
        self, client, session: Session, user: User, category: Category
    ):
        # Regresión: un ciclo con deuda inicial capturada al crear la tarjeta
        # (caso #8) tiene total_amount fijado a mano, sin transacciones reales
        # atrás. Si se dejaba registrar un gasto con una fecha que cae en ese
        # ciclo ya cerrado, recalculate_cycle_total pisaba ese monto en vez de
        # sumarle — y borrar esa transacción después lo dejaba en $0.
        create = client.post(
            "/api/v1/cards",
            json={
                "name": "Amex Platino", "bank": "Amex", "last_four": "4092",
                "credit_limit": "10000.00", "statement_day": 15, "payment_term_days": 30,
                "initial_balance": "5316.69", "initial_due_date": "2030-09-15",
            },
            headers=auth_headers(user),
        )
        card_id = create.json()["id"]

        cycles = client.get(f"/api/v1/cards/{card_id}/cycles", headers=auth_headers(user)).json()
        closed_cycle = next(c for c in cycles if c["status"] == "CLOSED")

        response = client.post(
            "/api/v1/transactions",
            json={
                "amount": "1308.27", "category_id": category.id, "description": "Compra de prueba",
                "transaction_date": closed_cycle["start_date"],
                "payment_method": "CREDIT", "credit_card_id": card_id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 400

        # El monto de la deuda inicial no se debe haber tocado.
        unchanged = session.get(BillingCycle, closed_cycle["id"])
        session.refresh(unchanged)
        assert unchanged.total_amount == Decimal("5316.69")
