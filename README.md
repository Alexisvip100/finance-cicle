# Ciclos — backend

FastAPI + SQLAlchemy. La lógica de dominio vive en `app/services/`, no en routers.

## Setup

```bash
cd backend-movile
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dev y tests usan SQLite en archivo/memoria por defecto (`DATABASE_URL` en `app/core/config.py`),
así que no necesitas PostgreSQL corriendo para desarrollar. Cuando conectes a PostgreSQL real:

```bash
pip install -r requirements-postgres.txt
export DATABASE_URL="postgresql://user:pass@localhost:5432/ciclos"
```

## Correr el servidor

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Docs interactivas en `http://localhost:8000/docs`.

## Correr con Docker (backend + PostgreSQL)

No requiere Python ni PostgreSQL instalados localmente — solo Docker.

```bash
cd backend-movile
docker compose up --build
```

Esto levanta dos contenedores: `db` (PostgreSQL 16, con el volumen `pgdata` para que los
datos sobrevivan a un restart) y `api` (este backend, con `--reload` activo y el código
montado como volumen, así que los cambios se reflejan sin rebuildear la imagen). El
servidor queda igual que antes en `http://localhost:8000` — desde el teléfono en la misma
red usa la IP de tu máquina (ej. `http://192.168.1.193:8000`).

Las tablas se crean solas al arrancar (`Base.metadata.create_all()`, igual que en dev con
SQLite). Para bajar los contenedores sin perder los datos: `docker compose down`; para
borrar también el volumen de Postgres: `docker compose down -v`.

Postgres queda expuesto al host en el puerto `55432` (no `5432`, para no chocar con un
Postgres local que ya lo esté usando) — `psql -h localhost -p 55432 -U ciclos -d ciclos`
(password `ciclos`). Entre contenedores (`api` → `db`) siempre se usa el puerto interno
`5432`, sin importar ese remapeo.

## Deploy en Render

Este repo trae `render.yaml` (Blueprint): un web service Docker + una base Postgres, ya
enlazados (`DATABASE_URL` se pasa solo). Pasos en [render.com](https://render.com):

1. New → Blueprint → conecta este repo de GitHub.
2. Render detecta `render.yaml` y muestra los dos recursos (`ciclos-api` + `ciclos-db`) —
   dale Apply.
3. Espera el build (unos minutos la primera vez). La URL pública queda en el dashboard del
   servicio `ciclos-api` (algo como `https://ciclos-api.onrender.com`).

`SECRET_KEY` se genera solo (Render lo marca `generateValue: true`). En el plan free la
base de Postgres se borra a los 90 días de inactividad si no la usas — para un proyecto
personal en uso constante no es un problema, pero vale la pena saberlo.

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

## Estado actual (según el orden de desarrollo del spec, §11) — backend completo

- [x] 1. Modelo de datos (`app/models/`)
- [x] 2. `cycle_service` con tests
- [x] 3. `balance_service`, `flow_service` e `income_schedule` con tests
- [x] 4. Endpoints de auth, cuentas y tarjetas (`app/api/v1/auth.py`, `accounts.py`, `cards.py`)
- [x] 5. Endpoints de transacciones y pagos (`transactions.py`, `payments.py`) + `budget_service`
- [x] 6. Endpoints agregados: `/dashboard`, `/flow`, `/budget` (`aggregates.py`)
- [ ] 7-12. Frontend (React Native + Redux) — no iniciado

**91 tests pasando.** Cobertura de los 12 casos de prueba obligatorios del spec (§10):
todos excepto ninguno quedó sin al menos un test dedicado (#1, #2, #10, #12 en
`test_cycle_service.py`; #3 en `test_income_schedule.py`; #4 en `test_flow_service.py`
y `test_budget_service.py`; #5, #6 en `test_api/test_payments.py`; #7 en
`test_api/test_payments.py`; #8 en `test_api/test_cards.py`; #9 en `test_flow_service.py`
y `test_api/test_aggregates.py`; #11 en `test_cycle_service.py` y `test_api/test_transactions.py`).

## Endpoints

```
POST   /api/v1/auth/register
POST   /api/v1/auth/login

GET    /api/v1/accounts            POST /api/v1/accounts
GET    /api/v1/accounts/{id}       PATCH /api/v1/accounts/{id}       DELETE /api/v1/accounts/{id}

GET    /api/v1/cards               POST /api/v1/cards
GET    /api/v1/cards/{id}          PATCH /api/v1/cards/{id}          DELETE /api/v1/cards/{id}
GET    /api/v1/cards/{id}/cycles
GET    /api/v1/cards/{id}/cycles/{cycle_id}/transactions
POST   /api/v1/cards/{id}/payments
POST   /api/v1/cards/{id}/allocations
DELETE /api/v1/allocations/{id}

POST   /api/v1/transactions        GET /api/v1/transactions (?category_id&from_date&to_date)
DELETE /api/v1/transactions/{id}

GET    /api/v1/categories          POST /api/v1/categories
GET    /api/v1/categories/{id}     PATCH /api/v1/categories/{id}     DELETE /api/v1/categories/{id}

GET    /api/v1/fixed-expenses      POST /api/v1/fixed-expenses
GET    /api/v1/fixed-expenses/{id} PATCH /api/v1/fixed-expenses/{id} DELETE /api/v1/fixed-expenses/{id}

GET    /api/v1/incomes             POST /api/v1/incomes
GET    /api/v1/incomes/{id}        PATCH /api/v1/incomes/{id}        DELETE /api/v1/incomes/{id}

GET    /api/v1/dashboard
GET    /api/v1/flow?days=30|60|90
GET    /api/v1/budget?month=YYYY-MM
```

## Decisiones ya revisadas contigo

1. **`payments.source`** → confirmado: `source_type` (enum `ACCOUNT`/`ALLOCATION`) +
   `source_account_id` (FK, nullable, solo se llena si `source_type == ACCOUNT`). Se
   queda como está.
2. **Relación con `installment_plans`** → confirmado: solo `installment_plans.transaction_id`.
   Se quitó la columna `transactions.installment_plan_id` y el workaround `use_alter`
   que existía por la dependencia circular (ya no hay dependencia circular — `transactions`
   ya no referencia `installment_plans`). Para saber si una transacción originó un plan MSI,
   se consulta `InstallmentPlan.transaction_id == transaction.id`.
3. **MSI y `comprometido`** → confirmado: se queda así por ahora. El saldo pendiente de
   un plan MSI no cuenta dentro de `comprometido` (solo ciclos CLOSED/PARTIALLY_PAID);
   sí es visible en `/flow` y en `credit_pending` de `/budget`.
4. **Borrar tarjetas con historial** → confirmado: se queda bloqueado con 409, sin
   soft-delete por ahora.

## Notas pendientes (no requieren decisión todavía)

1. **Migraciones (Alembic)** todavía no están armadas — el modelo se crea con
   `Base.metadata.create_all()` (en `app/main.py` para dev, en tests vía fixture).
   Las armo cuando tengas un `DATABASE_URL` de Postgres definitivo para generar la
   migración inicial real.
2. **Auth es JWT simple sin refresh tokens** ni rate-limiting ni verificación de
   correo — suficiente para desarrollo, no para producción tal cual.
