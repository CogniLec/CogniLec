"""Isolated diarisation service (S20 follow-up, gap #17/#18).

Wraps pyannote.audio's speaker-diarization-3.1 pipeline behind a small HTTP
API, run as its own container with its own dependency set (numpy>=2,
pyannote.audio). This is deliberately NOT a Python import into the shared
`src/` codebase: pyannote.audio 4.x requires numpy>=2, which is
ABI-incompatible with the main repo's numpy 1.26.x pin and would break
opencv/umap/hdbscan there (see docs/gaps.md gap #15 for the same conflict
class, previously worked around for vLLM the same way — an isolated
docker-compose service rather than an in-process import).

The rest of the codebase talks to this service over HTTP via
`src/services/diarisation/http_backend.py`, mirroring how src/services/llm/
talks to the isolated vLLM container instead of importing it.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import boto3
from botocore.client import Config
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="lis-diarisation-service")

_pipeline: Any = None


class DiariseRequest(BaseModel):
    object_key: str | None = None
    audio_path: str | None = None
    bucket: str = os.environ.get("MINIO_BUCKET_AUDIO", "lis-audio")
    max_speakers: int = 5


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    speaker_index: int


def _get_pipeline() -> Any:
    global _pipeline
    if _pipeline is None:
        import torch
        from pyannote.audio import Pipeline

        hf_token = os.environ["HF_TOKEN"]
        _pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
        if torch.cuda.is_available():
            _pipeline.to(torch.device("cuda"))
    return _pipeline


def _s3_client() -> Any:
    endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
    scheme = "https" if secure else "http"
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{endpoint}",
        aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _resolve_audio_path(req: DiariseRequest, tmp_path: str) -> str:
    if req.audio_path:
        return req.audio_path
    if req.object_key:
        _s3_client().download_file(req.bucket, req.object_key, tmp_path)
        return tmp_path
    raise HTTPException(status_code=400, detail="one of object_key or audio_path is required")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/diarise", response_model=list[Segment])
def diarise(req: DiariseRequest) -> list[Segment]:
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        audio_path = _resolve_audio_path(req, tmp.name)
        try:
            pipeline = _get_pipeline()
        except Exception as exc:  # pragma: no cover - needs real pyannote/GPU
            raise HTTPException(status_code=500, detail=f"pipeline load failed: {exc}") from exc

        output = pipeline(audio_path, max_speakers=req.max_speakers)
        annotation = output.speaker_diarization

        label_to_index: dict[str, int] = {}
        segments: list[Segment] = []
        for turn, _, label in annotation.itertracks(yield_label=True):
            if label not in label_to_index:
                label_to_index[label] = len(label_to_index)
            segments.append(
                Segment(
                    start_ms=int(turn.start * 1000),
                    end_ms=int(turn.end * 1000),
                    speaker_index=label_to_index[label],
                )
            )
        return segments
