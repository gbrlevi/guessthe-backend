"""FastAPI app. Rodar com --workers 1 (estado em RAM)."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import http, ws

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="LDKQuiz Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(http.router)
app.include_router(ws.router)


@app.get("/")
def root() -> dict:
    return {"service": "ldkquiz-backend", "docs": "/docs"}
