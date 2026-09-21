"""ExternalASRService: hosted OpenAI-compatible transcription backend."""

from __future__ import annotations

import uuid

import httpx
import numpy as np
import pytest
from src.services.asr.external import ExternalASRError, ExternalASRService


def _svc(handler) -> ExternalASRService:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ExternalASRService("http://x/v1", "k", "whisper", "en", "v1", client=client)


AUDIO = np.zeros(16000 * 2, dtype=np.float32)


def test_segments_become_ordered_utterances() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/audio/transcriptions"
        assert req.headers["authorization"] == "Bearer k"
        return httpx.Response(
            200,
            json={
                "segments": [
                    {"text": " Hello", "start": 0, "end": 1},
                    {"text": "World", "start": 1, "end": 2},
                ]
            },
        )

    r = _svc(handler).transcribe_chunk(AUDIO, 16000, uuid.uuid4(), uuid.uuid4(), 3000)
    assert [u.text for u in r.utterances] == ["Hello", "World"]
    assert [u.sequence for u in r.utterances] == [3000, 3001]


def test_text_only_response_becomes_single_utterance() -> None:
    svc = _svc(lambda req: httpx.Response(200, json={"text": "just text"}))
    r = svc.transcribe_chunk(AUDIO, 16000, uuid.uuid4(), uuid.uuid4(), 0)
    assert len(r.utterances) == 1 and r.utterances[0].text == "just text"


def test_http_error_raises() -> None:
    svc = _svc(lambda req: httpx.Response(429, json={}))
    with pytest.raises(ExternalASRError):
        svc.transcribe_chunk(AUDIO, 16000, uuid.uuid4(), uuid.uuid4(), 0)
