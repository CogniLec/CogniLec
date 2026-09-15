"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from src.api.routes.sessions import router as sessions_router
from src.api.routes.subjects import router as subjects_router
from src.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.APP_NAME)
app.include_router(subjects_router)
app.include_router(sessions_router)
