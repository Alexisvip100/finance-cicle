from sqlalchemy.orm import Session

from app.models import User
from tests.conftest import auth_headers


class TestRegister:
    def test_registra_y_regresa_token(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "ana@example.com", "password": "supersegura123"},
        )
        assert response.status_code == 201
        assert "access_token" in response.json()

    def test_email_duplicado_regresa_409(self, client):
        payload = {"email": "ana@example.com", "password": "supersegura123"}
        client.post("/api/v1/auth/register", json=payload)
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 409


class TestLogin:
    def test_login_correcto_regresa_token(self, client):
        client.post("/api/v1/auth/register", json={"email": "ana@example.com", "password": "supersegura123"})
        response = client.post(
            "/api/v1/auth/login", json={"email": "ana@example.com", "password": "supersegura123"}
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_password_incorrecta_regresa_401(self, client):
        client.post("/api/v1/auth/register", json={"email": "ana@example.com", "password": "supersegura123"})
        response = client.post("/api/v1/auth/login", json={"email": "ana@example.com", "password": "otra-cosa"})
        assert response.status_code == 401


class TestProtectedEndpoints:
    def test_sin_token_regresa_401(self, client):
        response = client.get("/api/v1/accounts")
        assert response.status_code == 401

    def test_con_token_valido_regresa_200(self, client, session: Session, user: User):
        response = client.get("/api/v1/accounts", headers=auth_headers(user))
        assert response.status_code == 200
        assert response.json() == []


class TestMe:
    def test_regresa_el_usuario_del_token(self, client, user: User):
        response = client.get("/api/v1/auth/me", headers=auth_headers(user))
        assert response.status_code == 200
        assert response.json()["email"] == user.email

    def test_sin_token_regresa_401(self, client):
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_regresa_monthly_spending_goal_nulo_por_defecto(self, client, user: User):
        response = client.get("/api/v1/auth/me", headers=auth_headers(user))
        assert response.json()["monthly_spending_goal"] is None


class TestUpdateMe:
    def test_configura_la_meta_de_gasto_mensual(self, client, user: User):
        response = client.patch(
            "/api/v1/auth/me", json={"monthly_spending_goal": "8000.00"}, headers=auth_headers(user)
        )
        assert response.status_code == 200
        assert response.json()["monthly_spending_goal"] == "8000.00"

        confirm = client.get("/api/v1/auth/me", headers=auth_headers(user))
        assert confirm.json()["monthly_spending_goal"] == "8000.00"

    def test_puede_quitar_la_meta_mandando_null(self, client, user: User):
        client.patch("/api/v1/auth/me", json={"monthly_spending_goal": "8000.00"}, headers=auth_headers(user))
        response = client.patch("/api/v1/auth/me", json={"monthly_spending_goal": None}, headers=auth_headers(user))
        assert response.json()["monthly_spending_goal"] is None
