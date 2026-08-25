from datetime import date
from decimal import Decimal

from app.models import Account, Category, User
from app.models.transaction import PaymentMethod
from tests.conftest import auth_headers, make_transaction


class TestCategoriesCrud:
    def test_crear_listar_actualizar_borrar(self, client, user: User):
        create = client.post(
            "/api/v1/categories",
            json={"name": "Entretenimiento", "monthly_limit": "1500.00"},
            headers=auth_headers(user),
        )
        assert create.status_code == 201
        category_id = create.json()["id"]

        listed = client.get("/api/v1/categories", headers=auth_headers(user))
        assert len(listed.json()) == 1

        patched = client.patch(
            f"/api/v1/categories/{category_id}", json={"monthly_limit": "2000.00"}, headers=auth_headers(user)
        )
        assert patched.json()["monthly_limit"] == "2000.00"

        deleted = client.delete(f"/api/v1/categories/{category_id}", headers=auth_headers(user))
        assert deleted.status_code == 204

    def test_un_usuario_no_ve_categorias_de_otro(self, client, session, user: User):
        from app.models import User as UserModel

        other = UserModel(email="otro@example.com", password_hash="x")
        session.add(other)
        session.flush()

        create = client.post("/api/v1/categories", json={"name": "Comida"}, headers=auth_headers(user))
        category_id = create.json()["id"]

        response = client.get(f"/api/v1/categories/{category_id}", headers=auth_headers(other))
        assert response.status_code == 404

    def test_no_se_puede_borrar_una_categoria_con_gastos_registrados(
        self, client, session, user: User, account: Account, category: Category
    ):
        make_transaction(
            session, user, category,
            amount=Decimal("150.00"), transaction_date=date(2000, 1, 5), cash_flow_date=date(2000, 1, 5),
            payment_method=PaymentMethod.DEBIT, account_id=account.id,
        )

        response = client.delete(f"/api/v1/categories/{category.id}", headers=auth_headers(user))
        assert response.status_code == 409
