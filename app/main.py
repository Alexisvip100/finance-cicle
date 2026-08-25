from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.database import Base, engine

# Dev-only: crea las tablas si no existen. En producción esto lo reemplazan
# las migraciones de Alembic (ver README, sección de esquema pendiente).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ciclos API")
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health_check():
    return {"status": "ok"}
