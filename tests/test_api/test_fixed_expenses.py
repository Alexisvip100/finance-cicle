from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, Category, User
from tests.conftest import auth_headers, make_card


class TestFixedExpensesCrud:
    def test_crear_requiere_exactamente_una_fuente(
        self, client, user: User, account: Account, category: Category
    ):
        both = client.post(
            "/api/v1/fixed-expenses",
            json={
                "name": "Renta", "amount": "18500.00", "day_of_month": 1,
                "category_id": category.id, "account_id": account.id, "credit_card_id": 1,
            },
            headers=auth_headers(user),
        )
        assert both.status_code == 422

        neither = client.post(
            "/api/v1/fixed-expenses",
            json={"name": "Renta", "amount": "18500.00", "day_of_month": 1, "category_id": category.id},
            headers=auth_headers(user),
        )
        assert neither.status_code == 422

    def test_crear_listar_y_desactivar(self, client, user: User, account: Account, category: Category):
        create = client.post(
            "/api/v1/fixed-expenses",
            json={
                "name": "Spotify", "amount": "129.00", "day_of_month": 16,
                "category_id": category.id, "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        assert create.status_code == 201
        fixed_id = create.json()["id"]

        listed = client.get("/api/v1/fixed-expenses", headers=auth_headers(user))
        assert len(listed.json()) == 1

        patched = client.patch(
            f"/api/v1/fixed-expenses/{fixed_id}", json={"is_active": False}, headers=auth_headers(user)
        )
        assert patched.json()["is_active"] is False


class TestPayFixedExpense:
    def test_pagar_gasto_fijo_con_cuenta_crea_transaccion_y_descuenta_saldo(
        self, client, session: Session, user: User, account: Account, category: Category
    ):
        create = client.post(
            "/api/v1/fixed-expenses",
            json={
                "name": "Renta", "amount": "8500.00", "day_of_month": 1,
                "category_id": category.id, "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        fixed_id = create.json()["id"]
        balance_before = Decimal(str(account.balance))

        response = client.post(f"/api/v1/fixed-expenses/{fixed_id}/pay", json={}, headers=auth_headers(user))
        assert response.status_code == 201
        body = response.json()
        assert body["fixed_expense_id"] == fixed_id
        assert body["amount"] == "8500.00"
        assert body["account_id"] == account.id

        session.refresh(account)
        assert account.balance == balance_before - Decimal("8500.00")

        history = client.get(
            "/api/v1/transactions", params={"only_fixed_expenses": True}, headers=auth_headers(user)
        )
        assert len(history.json()) == 1
        assert history.json()[0]["fixed_expense_id"] == fixed_id

    def test_pagar_gasto_fijo_con_tarjeta_usa_ciclo_actual(self, client, session: Session, user: User, category: Category):
        card = make_card(session, user, statement_day=25, payment_term_days=20, name="Amex")
        create = client.post(
            "/api/v1/fixed-expenses",
            json={
                "name": "Netflix", "amount": "249.00", "day_of_month": 5,
                "category_id": category.id, "credit_card_id": card.id,
            },
            headers=auth_headers(user),
        )
        fixed_id = create.json()["id"]

        response = client.post(f"/api/v1/fixed-expenses/{fixed_id}/pay", json={}, headers=auth_headers(user))
        assert response.status_code == 201
        body = response.json()
        assert body["credit_card_id"] == card.id
        assert body["billing_cycle_id"] is not None

    def test_no_se_puede_pagar_un_gasto_fijo_inactivo(self, client, user: User, account: Account, category: Category):
        create = client.post(
            "/api/v1/fixed-expenses",
            json={
                "name": "Renta", "amount": "8500.00", "day_of_month": 1,
                "category_id": category.id, "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        fixed_id = create.json()["id"]
        client.patch(f"/api/v1/fixed-expenses/{fixed_id}", json={"is_active": False}, headers=auth_headers(user))

        response = client.post(f"/api/v1/fixed-expenses/{fixed_id}/pay", json={}, headers=auth_headers(user))
        assert response.status_code == 400

    def test_pagar_con_cuenta_borrada_regresa_404_en_vez_de_tronar(
        self, client, session: Session, user: User, account: Account, category: Category
    ):
        # Regresión: una cuenta borrada (por una vía que no pase por el guard
        # de accounts.py, ej. datos ya corrompidos) deja account_id colgando
        # — pagar debía dar 404 claro, no un 500 sin explicación.
        create = client.post(
            "/api/v1/fixed-expenses",
            json={
                "name": "Spotify", "amount": "129.00", "day_of_month": 16,
                "category_id": category.id, "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        fixed_id = create.json()["id"]

        session.delete(account)
        session.flush()

        response = client.post(f"/api/v1/fixed-expenses/{fixed_id}/pay", json={}, headers=auth_headers(user))
        assert response.status_code == 404
