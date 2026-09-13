"""S33 — Greeting keyword detection (session-start/boundary signal only).

MUST NEVER write to utterances.speaker_tag, is_relevant, or filter_reason —
this reverses the original design intent and is a hard invariant (FR-2.4).
This module is read-only with respect to utterance rows: it only reads
`id`, `seq`, `text`, `start_ms`, `end_ms` and returns a result object.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel

GREETING_CONFIG_PATH = Path("config/greeting_keywords.yaml")


class GreetingMatch(BaseModel):
    utterance_id: uuid.UUID
    seq: int
    matched_keyword: str
    language: str
    start_ms: int
    end_ms: int


class GreetingDetectionResult(BaseModel):
    session_id: uuid.UUID
    matches: list[GreetingMatch]
    has_greeting: bool
    session_start_boundary: int | None


class UtteranceLike(Protocol):
    id: uuid.UUID
    seq: int
    text: str
    start_ms: int
    end_ms: int


@lru_cache(maxsize=1)
def _load_config(path: str = str(GREETING_CONFIG_PATH)) -> dict[str, list[re.Pattern[str]]]:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    compiled: dict[str, list[re.Pattern[str]]] = {}
    for language, entries in raw.get("keywords", {}).items():
        compiled[language] = [re.compile(entry["pattern"], re.IGNORECASE) for entry in entries]
    return compiled


def detect_greetings(
    session_id: uuid.UUID,
    utterances: Sequence[UtteranceLike],
    config_path: str = str(GREETING_CONFIG_PATH),
) -> GreetingDetectionResult:
    """Scan utterance text for configured greeting keywords.

    Pure function — takes a list of utterance-like objects and returns a
    result; never mutates the inputs or touches speaker_tag/is_relevant.
    """
    patterns_by_language = _load_config(config_path)
    matches: list[GreetingMatch] = []

    for utt in utterances:
        for language, patterns in patterns_by_language.items():
            for pattern in patterns:
                match = pattern.search(utt.text)
                if match:
                    matches.append(
                        GreetingMatch(
                            utterance_id=utt.id,
                            seq=utt.seq,
                            matched_keyword=match.group(0),
                            language=language,
                            start_ms=utt.start_ms,
                            end_ms=utt.end_ms,
                        )
                    )

    session_start_boundary = min((m.seq for m in matches), default=None)
    return GreetingDetectionResult(
        session_id=session_id,
        matches=matches,
        has_greeting=bool(matches),
        session_start_boundary=session_start_boundary,
    )
