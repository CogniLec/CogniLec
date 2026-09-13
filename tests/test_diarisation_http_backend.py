"""Tests for `HTTPDiarisationBackend` (gap #17/#18 follow-up).

The isolated diarisation service (`services/diarisation-service/`) needs a
real GPU + pyannote weights + HF access to actually run, none of which this
sandbox has running as a container. The HTTP client logic itself -- request
shape, response parsing, error propagation -- is genuinely exercised here
against `httpx.MockTransport`, the same injection point already used for
`OpenverseClient` (tests/test_s62_image_retrieval.py) and `RerankerClient`.
"""

from __future__ import annotations

import httpx
import pytest
from src.core.config import Settings
from src.services.diarisation.http_backend import (
    HTTPDiarisationBackend,
    get_diarisation_backend,
)


def _client(handler: httpx.MockTransport | None = None, **overrides: object) -> httpx.Client:
    transport = handler or httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    return httpx.Client(transport=transport, base_url="http://diarisation:8100", **overrides)


def test_diarise_returns_parsed_segments():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/diarise"
        body = request.read()
        assert b"audio.wav" in body
        return httpx.Response(
            200,
            json=[
                {"start_ms": 0, "end_ms": 1000, "speaker_index": 0},
                {"start_ms": 1000, "end_ms": 2500, "speaker_index": 1},
            ],
        )

    backend = HTTPDiarisationBackend(
        settings=Settings(), client=_client(httpx.MockTransport(handler))
    )
    segments = backend.diarise("audio.wav", max_speakers=5)

    assert len(segments) == 2
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 1000
    assert segments[0].speaker_index == 0
    assert segments[1].speaker_index == 1


def test_diarise_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "pipeline load failed"})

    backend = HTTPDiarisationBackend(
        settings=Settings(), client=_client(httpx.MockTransport(handler))
    )
    with pytest.raises(httpx.HTTPStatusError):
        backend.diarise("audio.wav", max_speakers=5)


def test_diarise_empty_segments_on_silent_audio():
    backend = HTTPDiarisationBackend(settings=Settings(), client=_client())
    assert backend.diarise("silence.wav", max_speakers=5) == []


def test_get_diarisation_backend_returns_none_when_disabled():
    settings = Settings(DIARISATION_ENABLED=False)
    assert get_diarisation_backend(settings) is None


def test_get_diarisation_backend_returns_http_backend_when_enabled():
    settings = Settings(DIARISATION_ENABLED=True)
    backend = get_diarisation_backend(settings)
    assert isinstance(backend, HTTPDiarisationBackend)


@pytest.mark.skip(
    reason=(
        "requires the real services/diarisation-service container running with "
        "GPU + pyannote weights + a valid HF_TOKEN — not available in this "
        "sandbox (see docs/gaps.md gap #18); the HTTP client logic itself is "
        "covered by the mocked tests above"
    )
)
def test_diarise_against_real_running_service():
    pass
