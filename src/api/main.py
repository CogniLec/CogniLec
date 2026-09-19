"""Production FastAPI app assembly.

Every route module under src/api/routes/ was, until now, only ever mounted
individually inside test fixtures (see e.g. tests/test_manual_review_app_study_api.py's
_build_app) -- no src/main.py assembling them into one running app existed
anywhere in this repo. This is that assembly, wiring every router at the
prefix its own tests already exercise it at.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import (
    audio_upload,
    auth,
    chunks,
    cold_start,
    coverage,
    dashboard,
    notes,
    presigned,
    search,
    session_stream,
    sessions,
    study,
    subjects,
    syllabus_upload,
    topics,
    transcript,
    uploads,
)

app = FastAPI(title="Lecture Intelligence System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    audio_upload.router,
    auth.router,
    chunks.router,
    cold_start.router,
    coverage.router,
    dashboard.router,
    notes.router,
    presigned.router,
    search.router,
    session_stream.router,
    sessions.router,
    study.router,
    subjects.router,
    syllabus_upload.router,
    topics.router,
    transcript.router,
    uploads.router,
):
    app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
