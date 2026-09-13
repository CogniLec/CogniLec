"""HTTP `DiarisationBackend` calling the isolated diarisation service (gap #17/#18).

pyannote.audio cannot be imported into this shared codebase (numpy>=2 ABI
conflict — see `pyannote_backend.py`'s docstring and docs/gaps.md gap #15),
so the real production backend is this thin HTTP client against
`services/diarisation-service/`, a separate deployable with its own
dependency set. This mirrors how `src/services/llm/router.py` talks to the
isolated vLLM container over HTTP instead of importing it.

Only stdlib/httpx is imported here — never pyannote.
"""

from __future__ import annotations

import httpx
from src.core.config import Settings, get_settings
from src.services.diarisation.worker import DiarisationBackend, DiarisationSegment


class HTTPDiarisationSegment:
    def __init__(self, start_ms: int, end_ms: int, speaker_index: int) -> None:
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.speaker_index = speaker_index


class HTTPDiarisationBackend(DiarisationBackend):
    """Calls the isolated diarisation service's `POST /diarise` endpoint."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self._settings.DIARISATION_SERVICE_URL, timeout=300.0
        )

    def diarise(self, audio_path: str, max_speakers: int) -> list[DiarisationSegment]:
        response = self._client.post(
            "/diarise",
            json={"audio_path": audio_path, "max_speakers": max_speakers},
        )
        response.raise_for_status()
        return [
            HTTPDiarisationSegment(
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                speaker_index=item["speaker_index"],
            )
            for item in response.json()
        ]


def get_diarisation_backend(settings: Settings | None = None) -> DiarisationBackend | None:
    """Production wiring point: the real `DiarisationBackend` for `DiarisationWorker`.

    Returns `None` (single-speaker/UNKNOWN fallback, see worker.py) when
    diarisation is disabled, so callers can pass this straight into
    `DiarisationWorker(session_factory, backend=get_diarisation_backend())`.
    """
    settings = settings or get_settings()
    if not settings.DIARISATION_ENABLED:
        return None
    return HTTPDiarisationBackend(settings=settings)
