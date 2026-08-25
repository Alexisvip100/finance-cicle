from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountType, Category, User
from app.models.billing_cycle import CycleStatus
from app.models.income import IncomeFrequency
from tests.conftest import auth_headers, make_card, make_cycle, make_fixed_expense, make_income


class TestDashboard:
    def test_incluye_disponible_y_tarjetas(self, client, session: Session, user: User, account: Account):
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        response = client.get("/api/v1/dashboard", headers=auth_headers(user))
        assert response.status_code == 200
        body = response.json()

        assert body["accounts_total"] == "60000.00"
        assert body["committed"] == "12000.00"
        assert body["available"] == "48000.00"
        assert len(body["cards"]) == 1
        assert body["cards"][0]["current_cycle"] is not None
        assert body["cards"][0]["pending_cycle"]["total_amount"] == "12000.00"

    def test_proximas_salidas_incluye_fijos_cercanos(
        self, client, session: Session, user: User, account: Account, category: Category
    ):
        soon = date.today() + timedelta(days=3)
        make_fixed_expense(session, user, category, name="Internet", amount=Decimal("500.00"), day_of_month=soon.day)

        response = client.get("/api/v1/dashboard", headers=auth_headers(user))
        body = response.json()
        labels = [o["label"] for o in body["upcoming_outflows"]]
        assert "Internet" in labels


class TestFlow:
    def test_rechaza_dias_invalidos(self, client, user: User):
        response = client.get("/api/v1/flow", params={"days": 45}, headers=auth_headers(user))
        assert response.status_code == 400

    def test_acepta_30_60_90_y_agrupa_por_semana(self, client, user: User, account: Account, category, session: Session):
        soon = date.today() + timedelta(days=10)
        make_fixed_expense(session, user, category, name="Spotify", amount=Decimal("129.00"), day_of_month=soon.day)

        for days in (30, 60, 90):
            response = client.get("/api/v1/flow", params={"days": days}, headers=auth_headers(user))
            assert response.status_code == 200
            body = response.json()
            assert body["starting_balance"] == "60000.00"
            assert isinstance(body["weeks"], list)

    def test_marca_deficit_risk(self, client, session: Session, user: User, account: Account):
        account.balance = Decimal("500.00")
        session.flush()
        card = make_card(session, user, statement_day=25, payment_term_days=20)
        due_soon = date.today() + timedelta(days=5)
        make_cycle(
            session, card, start=date(2000, 1, 1), end=date(2000, 2, 1), due=due_soon,
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        response = client.get("/api/v1/flow", params={"days": 30}, headers=auth_headers(user))
        body = response.json()
        assert body["deficit_risk"] is True
        assert body["deficit_date"] == due_soon.isoformat()


class TestBudget:
    def test_rechaza_formato_de_mes_invalido(self, client, user: User):
        response = client.get("/api/v1/budget", params={"month": "2026/08"}, headers=auth_headers(user))
        assert response.status_code == 422

    def test_regresa_resumen_por_categoria(
        self, client, session: Session, user: User, account: Account, category: Category
    ):
        today = date.today()
        month_key = f"{today.year:04d}-{today.month:02d}"

        client.post(
            "/api/v1/transactions",
            json={
                "amount": "500.00", "category_id": category.id, "description": "Compra de prueba",
                "transaction_date": today.isoformat(),
                "payment_method": "CASH", "account_id": account.id,
            },
            headers=auth_headers(user),
        )

        response = client.get("/api/v1/budget", params={"month": month_key}, headers=auth_headers(user))
        assert response.status_code == 200
        body = response.json()
        assert body["month"] == month_key
        assert body["total_spent"] == "500.00"
        assert body["categories"][0]["category_name"] == "Comida"

    def test_gastos_sin_categoria_aparecen_como_sin_categoria(
        self, client, session: Session, user: User, account: Account
    ):
        today = date.today()
        month_key = f"{today.year:04d}-{today.month:02d}"

        client.post(
            "/api/v1/transactions",
            json={
                "amount": "300.00", "description": "Café", "transaction_date": today.isoformat(),
                "payment_method": "CASH", "account_id": account.id,
            },
            headers=auth_headers(user),
        )

        response = client.get("/api/v1/budget", params={"month": month_key}, headers=auth_headers(user))
        body = response.json()
        assert body["total_spent"] == "300.00"
        sin_categoria = next(c for c in body["categories"] if c["category_id"] is None)
        assert sin_categoria["category_name"] == "Sin categoría"
        assert sin_categoria["spent"] == "300.00"

    def test_meta_de_gasto_y_ahorro_proyectado(
        self, client, session: Session, user: User, account: Account, category: Category
    ):
        # Ejemplo real del usuario: ingreso de 7000 quincenal (14000 al mes),
        # meta de gasto de 8000 -> ahorro proyectado de 6000 si no se gasta nada.
        make_income(session, user, account, amount=Decimal("7000.00"), frequency=IncomeFrequency.BIWEEKLY, payment_days=[15, "LAST_DAY"])
        client.patch("/api/v1/auth/me", json={"monthly_spending_goal": "8000.00"}, headers=auth_headers(user))

        today = date.today()
        month_key = f"{today.year:04d}-{today.month:02d}"
        response = client.get("/api/v1/budget", params={"month": month_key}, headers=auth_headers(user))
        body = response.json()

        assert body["spending_goal"] == "8000.00"
        assert body["income_this_month"] == "14000.00"
        assert body["projected_savings"] == "14000.00"  # nada gastado todavía

        client.post(
            "/api/v1/transactions",
            json={
                "amount": "8000.00", "category_id": category.id, "description": "Compra de prueba",
                "transaction_date": today.isoformat(),
                "payment_method": "CASH", "account_id": account.id,
            },
            headers=auth_headers(user),
        )

        response = client.get("/api/v1/budget", params={"month": month_key}, headers=auth_headers(user))
        body = response.json()
        assert body["total_spent"] == "8000.00"
        assert body["projected_savings"] == "6000.00"  # 14000 - 8000
