from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import User
from app.models.billing_cycle import CycleStatus
from tests.conftest import auth_headers, make_cycle


class TestCreateCard:
    def test_crear_precalcula_ciclos_de_inmediato(self, client, user: User):
        response = client.post(
            "/api/v1/cards",
            json={
                "name": "Amex Platino",
                "bank": "Amex",
                "last_four": "4092",
                "credit_limit": "45000.00",
                "statement_day": 25,
                "payment_term_days": 20,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201

    def test_deuda_preexistente_que_coincide_con_el_ciclo_actual_no_choca(self, client, user: User):
        # Bug real: si el ciclo de la deuda inicial resuelve al mismo start_date
        # que el ciclo "actual" que genera generate_cycles, insertar ambos
        # violaba la unique constraint (credit_card_id, start_date) y tiraba
        # TODA la creación de la tarjeta (commit con rollback, nada se guardaba).
        payment_term_days = 20
        due_date = date.today() + timedelta(days=payment_term_days + 1)
        response = client.post(
            "/api/v1/cards",
            json={
                "name": "Amex Platino",
                "bank": "Amex",
                "last_four": "4092",
                "credit_limit": "45000.00",
                "statement_day": 15,
                "payment_term_days": payment_term_days,
                "initial_balance": "1000.00",
                "initial_due_date": due_date.isoformat(),
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
        card_id = response.json()["id"]

        cycles = client.get(f"/api/v1/cards/{card_id}/cycles", headers=auth_headers(user)).json()
        starts = [c["start_date"] for c in cycles]
        assert len(starts) == len(set(starts))  # sin duplicados
        assert any(c["status"] == "CLOSED" and c["total_amount"] == "1000.00" for c in cycles)


class TestCardDetail:
    def test_incluye_ciclo_actual_por_pagar_apartado_y_msi(
        self, client, session: Session, user: User
    ):
        create = client.post(
            "/api/v1/cards",
            json={
                "name": "Amex Platino", "bank": "Amex", "last_four": "4092",
                "credit_limit": "45000.00", "statement_day": 25, "payment_term_days": 20,
            },
            headers=auth_headers(user),
        )
        card_id = create.json()["id"]

        from app.models.credit_card import CreditCard

        card = session.get(CreditCard, card_id)
        # Fecha muy en el pasado a propósito: crear la tarjeta ya disparó
        # generate_cycles() anclado al "hoy" real de la máquina, así que un
        # ciclo cercano a la fecha real podría chocar con uno auto-generado.
        pending = make_cycle(
            session, card, start=date(2000, 7, 25), end=date(2000, 8, 25), due=date(2000, 9, 14),
            status=CycleStatus.CLOSED, total_amount=Decimal("12000.00"),
        )

        from app.models.savings_allocation import SavingsAllocation
        from app.models.account import Account, AccountType

        source_account = Account(user_id=user.id, name="Débito BBVA", type=AccountType.DEBIT, balance=Decimal("60000"))
        session.add(source_account)
        session.flush()
        session.add(
            SavingsAllocation(
                credit_card_id=card.id, billing_cycle_id=pending.id, amount=Decimal("8500.00"),
                source_account_id=source_account.id,
            )
        )
        session.flush()

        detail = client.get(f"/api/v1/cards/{card_id}", headers=auth_headers(user))
        body = detail.json()

        assert body["current_cycle"] is not None
        assert body["pending_cycle"]["id"] == pending.id
        assert body["allocated_for_pending_cycle"] == "8500.00"

    def test_credito_disponible_baja_con_el_ciclo_abierto_aunque_ya_pagaste_el_anterior(
        self, client, session: Session, user: User
    ):
        # Caso real reportado: límite 10000, agosto se gastó y pagó 5317.00
        # completo (ciclo PAID, ya no debe nada), después del corte se
        # gastaron 1308.27 más (ciclo actual, todavía abierto). El crédito
        # disponible debe reflejar SOLO lo que sigue ocupando el límite: los
        # 1308.27 del ciclo abierto — 10000 - 1308.27 = 8691.73.
        create = client.post(
            "/api/v1/cards",
            json={
                "name": "Amex Platino", "bank": "Amex", "last_four": "4092",
                "credit_limit": "10000.00", "statement_day": 25, "payment_term_days": 20,
            },
            headers=auth_headers(user),
        )
        card_id = create.json()["id"]

        from app.models.credit_card import CreditCard

        card = session.get(CreditCard, card_id)
        make_cycle(
            session, card, start=date(2000, 6, 25), end=date(2000, 7, 25), due=date(2000, 8, 14),
            status=CycleStatus.PAID, total_amount=Decimal("5317.00"), paid_amount=Decimal("5317.00"),
        )

        detail_before = client.get(f"/api/v1/cards/{card_id}", headers=auth_headers(user)).json()
        current_cycle_id = detail_before["current_cycle"]["id"]
        from app.models.billing_cycle import BillingCycle

        current_cycle = session.get(BillingCycle, current_cycle_id)
        current_cycle.total_amount = Decimal("1308.27")
        session.flush()

        detail = client.get(f"/api/v1/cards/{card_id}", headers=auth_headers(user)).json()
        assert detail["available_credit"] == "8691.73"


class TestUpdateCard:
    def test_caso_12_cambiar_corte_regenera_ciclos_abiertos_sin_tocar_cerrados(
        self, client, session: Session, user: User
    ):
        create = client.post(
            "/api/v1/cards",
            json={
                "name": "Amex Platino", "bank": "Amex", "last_four": "4092",
                "credit_limit": "45000.00", "statement_day": 25, "payment_term_days": 20,
            },
            headers=auth_headers(user),
        )
        card_id = create.json()["id"]

        from app.models.credit_card import CreditCard

        card = session.get(CreditCard, card_id)
        # Año 2000 a propósito: nunca choca con los ciclos que generate_cycles
        # ya creó al crear la tarjeta, anclado al "hoy" real de la máquina.
        closed = make_cycle(
            session, card, start=date(2000, 5, 25), end=date(2000, 6, 25), due=date(2000, 7, 15),
            status=CycleStatus.CLOSED, total_amount=Decimal("1000.00"),
        )

        response = client.patch(
            f"/api/v1/cards/{card_id}", json={"statement_day": 10}, headers=auth_headers(user)
        )
        assert response.status_code == 200
        assert response.json()["statement_day"] == 10

        cycles = client.get(f"/api/v1/cards/{card_id}/cycles", headers=auth_headers(user)).json()
        open_cycles = [c for c in cycles if c["status"] == "OPEN"]
        closed_cycles = [c for c in cycles if c["id"] == closed.id]

        assert all(int(c["start_date"].split("-")[2]) == 10 for c in open_cycles)
        assert closed_cycles[0]["start_date"] == "2000-05-25"  # intacto


class TestDeleteCard:
    def test_no_se_puede_borrar_una_tarjeta_con_ciclos(self, client, session: Session, user: User):
        create = client.post(
            "/api/v1/cards",
            json={
                "name": "Amex Platino", "bank": "Amex", "last_four": "4092",
                "credit_limit": "45000.00", "statement_day": 25, "payment_term_days": 20,
            },
            headers=auth_headers(user),
        )
        card_id = create.json()["id"]
        response = client.delete(f"/api/v1/cards/{card_id}", headers=auth_headers(user))
        assert response.status_code == 409
