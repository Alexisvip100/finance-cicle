from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.database import Base, engine

# Dev-only: crea las tablas si no existen. En producción esto lo reemplazan
# las migraciones de Alembic (ver README, sección de esquema pendiente).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ciclos API")

# La app móvil (Expo Go / build nativa) no pasa por CORS — solo el navegador lo
# exige. Sin esto, web-movile (otro origen) no puede llamar a esta API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    # Cubre tanto el dominio de producción (finances-web.vercel.app) como los
    # preview deploys (finances-web-git-*.vercel.app, finances-web-*.vercel.app)
    # sin tener que hardcodear cada URL que Vercel genera.
    allow_origin_regex=r"https://finances-web(-[a-z0-9-]+)?\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health_check():
    return {"status": "ok"}
