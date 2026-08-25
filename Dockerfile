FROM python:3.11-slim

WORKDIR /app

# libpq5: librería runtime que psycopg2-binary necesita para hablar con Postgres.
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-postgres.txt

COPY . .

EXPOSE 8000

# Forma shell (no exec) a propósito: Render inyecta $PORT y hay que expandirlo
# en runtime; localmente (docker compose) cae al 8000 de siempre.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
