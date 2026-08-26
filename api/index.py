"""Entrypoint que Vercel reconoce (@vercel/python detecta `app` en /api/*.py
como ASGI) — el resto del backend (app/) no sabe ni le importa que corre en
Vercel, sigue siendo el mismo FastAPI de siempre."""

from app.main import app
