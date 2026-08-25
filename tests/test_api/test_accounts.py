from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, User
from tests.conftest import auth_headers, make_fixed_expense


class TestAccountsCrud:
    def test_crear_y_listar(self, client, user: User):
        response = client.post(
            "/api/v1/accounts",
            json={"name": "Efectivo", "type": "CASH", "balance": "2500.00"},
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        created = response.json()
        assert created["name"] == "Efectivo"
        assert created["balance"] == "2500.00"

        listed = client.get("/api/v1/accounts", headers=auth_headers(user))
        assert len(listed.json()) == 1

    def test_actualizar_saldo(self, client, user: User):
        create = client.post(
            "/api/v1/accounts",
            json={"name": "Débito BBVA", "type": "DEBIT", "balance": "60000.00"},
            headers=auth_headers(user),
        )
        account_id = create.json()["id"]

        patched = client.patch(
            f"/api/v1/accounts/{account_id}",
            json={"balance": "58000.00"},
            headers=auth_headers(user),
        )
        assert patched.status_code == 200
        assert patched.json()["balance"] == "58000.00"

    def test_borrar(self, client, user: User):
        create = client.post(
            "/api/v1/accounts", json={"name": "Efectivo", "type": "CASH"}, headers=auth_headers(user)
        )
        account_id = create.json()["id"]

        deleted = client.delete(f"/api/v1/accounts/{account_id}", headers=auth_headers(user))
        assert deleted.status_code == 204

        missing = client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers(user))
        assert missing.status_code == 404

    def test_no_se_puede_borrar_una_cuenta_con_gastos_fijos_asociados(
        self, client, session: Session, user: User, category: Category
    ):
        create = client.post(
            "/api/v1/accounts", json={"name": "Efectivo", "type": "CASH"}, headers=auth_headers(user)
        )
        account_id = create.json()["id"]

        fixed = make_fixed_expense(session, user, category, name="Spotify", amount=Decimal("129.00"), day_of_month=16)
        fixed.account_id = account_id
        session.flush()

        response = client.delete(f"/api/v1/accounts/{account_id}", headers=auth_headers(user))
        assert response.status_code == 409

    def test_un_usuario_no_puede_ver_cuentas_de_otro(self, client, session: Session, user: User):
        from app.models import User as UserModel

        other = UserModel(email="otro@example.com", password_hash="x")
        session.add(other)
        session.flush()

        create = client.post(
            "/api/v1/accounts", json={"name": "Efectivo", "type": "CASH"}, headers=auth_headers(user)
        )
        account_id = create.json()["id"]

        response = client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers(other))
        assert response.status_code == 404
