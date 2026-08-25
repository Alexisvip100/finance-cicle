from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, User
from tests.conftest import auth_headers


class TestIncomesCrud:
    def test_crear_quincenal_con_last_day(self, client, user: User, account: Account):
        response = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "15000.00", "frequency": "BIWEEKLY",
                "payment_days": [15, "LAST_DAY"], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        assert response.json()["payment_days"] == [15, "LAST_DAY"]

    def test_crear_con_semana_de_pago(self, client, user: User, account: Account):
        response = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7300.00", "frequency": "BIWEEKLY",
                "payment_days": [15, "WLAST-FRI"], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        assert response.json()["payment_days"] == [15, "WLAST-FRI"]

    def test_semana_de_pago_invalida_se_rechaza(self, client, user: User, account: Account):
        response = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7300.00", "frequency": "MONTHLY",
                "payment_days": ["W5-FRI"], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 422

    def test_crear_con_dia_ajustado(self, client, user: User, account: Account):
        response = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7000.00", "frequency": "BIWEEKLY",
                "payment_days": ["D15-ADJ", "WLAST-FRI"], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        assert response.json()["payment_days"] == ["D15-ADJ", "WLAST-FRI"]

    def test_dia_ajustado_invalido_se_rechaza(self, client, user: User, account: Account):
        response = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7000.00", "frequency": "MONTHLY",
                "payment_days": ["D32-ADJ"], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 422

    def test_dia_de_pago_invalido_se_rechaza(self, client, user: User, account: Account):
        response = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "15000.00", "frequency": "MONTHLY",
                "payment_days": [35], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 422

    def test_listar_y_desactivar(self, client, user: User, account: Account):
        create = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "15000.00", "frequency": "MONTHLY",
                "payment_days": [1], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        income_id = create.json()["id"]

        listed = client.get("/api/v1/incomes", headers=auth_headers(user))
        assert len(listed.json()) == 1

        patched = client.patch(
            f"/api/v1/incomes/{income_id}", json={"is_active": False}, headers=auth_headers(user)
        )
        assert patched.json()["is_active"] is False


class TestReceiveIncome:
    def test_recibir_hoy_abona_la_cuenta_y_crea_el_recibo(
        self, client, session: Session, user: User, account: Account
    ):
        create = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7000.00", "frequency": "MONTHLY",
                "payment_days": [15], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        income_id = create.json()["id"]
        balance_before = Decimal(str(account.balance))

        response = client.post(f"/api/v1/incomes/{income_id}/receive", json={}, headers=auth_headers(user))
        assert response.status_code == 201
        body = response.json()
        assert body["income_id"] == income_id
        assert body["amount"] == "7000.00"

        session.refresh(account)
        assert account.balance == balance_before + Decimal("7000.00")

    def test_recibir_con_fecha_y_monto_distinto(self, client, user: User, account: Account):
        create = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7000.00", "frequency": "MONTHLY",
                "payment_days": [15], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        income_id = create.json()["id"]

        response = client.post(
            f"/api/v1/incomes/{income_id}/receive",
            json={"received_date": "2026-07-15", "amount": "7500.00"},
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        assert response.json()["received_date"] == "2026-07-15"
        assert response.json()["amount"] == "7500.00"

    def test_no_se_puede_recibir_un_ingreso_inactivo(self, client, user: User, account: Account):
        create = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7000.00", "frequency": "MONTHLY",
                "payment_days": [15], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        income_id = create.json()["id"]
        client.patch(f"/api/v1/incomes/{income_id}", json={"is_active": False}, headers=auth_headers(user))

        response = client.post(f"/api/v1/incomes/{income_id}/receive", json={}, headers=auth_headers(user))
        assert response.status_code == 400

    def test_eliminar_recibo_revierte_el_abono(self, client, session: Session, user: User, account: Account):
        create = client.post(
            "/api/v1/incomes",
            json={
                "name": "Nómina", "amount": "7000.00", "frequency": "MONTHLY",
                "payment_days": [15], "account_id": account.id,
            },
            headers=auth_headers(user),
        )
        income_id = create.json()["id"]
        balance_before = Decimal(str(account.balance))

        receipt = client.post(f"/api/v1/incomes/{income_id}/receive", json={}, headers=auth_headers(user)).json()
        session.refresh(account)
        assert account.balance == balance_before + Decimal("7000.00")

        response = client.delete(f"/api/v1/incomes/receipts/{receipt['id']}", headers=auth_headers(user))
        assert response.status_code == 204

        session.refresh(account)
        assert account.balance == balance_before

        listed = client.get("/api/v1/incomes/receipts", headers=auth_headers(user)).json()
        assert listed == []

    def test_filtra_recibos_por_fecha_y_por_ingreso(self, client, user: User, account: Account):
        income1 = client.post(
            "/api/v1/incomes",
            json={
                "name": "Quincena 1", "amount": "7000.00", "frequency": "MONTHLY",
                "payment_days": [15], "account_id": account.id,
            },
            headers=auth_headers(user),
        ).json()["id"]
        income2 = client.post(
            "/api/v1/incomes",
            json={
                "name": "Quincena 2", "amount": "7300.00", "frequency": "MONTHLY",
                "payment_days": [28], "account_id": account.id,
            },
            headers=auth_headers(user),
        ).json()["id"]

        client.post(f"/api/v1/incomes/{income1}/receive", json={"received_date": "2026-07-15"}, headers=auth_headers(user))
        client.post(f"/api/v1/incomes/{income1}/receive", json={"received_date": "2026-08-15"}, headers=auth_headers(user))
        client.post(f"/api/v1/incomes/{income2}/receive", json={"received_date": "2026-08-28"}, headers=auth_headers(user))

        by_month = client.get(
            "/api/v1/incomes/receipts",
            params={"from_date": "2026-08-01", "to_date": "2026-08-31"},
            headers=auth_headers(user),
        ).json()
        assert len(by_month) == 2

        by_income = client.get(
            "/api/v1/incomes/receipts", params={"income_id": income1}, headers=auth_headers(user)
        ).json()
        assert len(by_income) == 2
        assert all(r["income_id"] == income1 for r in by_income)
