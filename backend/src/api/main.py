"""kb-API gateway entry point.

Единая точка входа FastAPI-приложения. Все routers подключаются через
include_router. См. ADR-0005 для обоснования выбора FastAPI.
"""

from fastapi import FastAPI

from src.api.v1.router import router as v1_router

app = FastAPI(
    title="reHome Knowledge Base API",
    description=(
        "Gateway модуля базы знаний reHome. "
        "Полный контракт — в docs/handoff/01_postanovka/04_openapi.yaml."
    ),
    version="1.0.0",
)

app.include_router(v1_router)
