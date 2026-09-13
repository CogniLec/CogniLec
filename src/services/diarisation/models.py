"""Pydantic v2 domain schemas for S20 diarisation and NFR-S4 audit (spec section 2)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class SpeakerTag(StrEnum):
    """Session-scoped anonymous speaker tags.

    NEVER linked across sessions.
    NEVER used as biometric identifiers.
    DROPPED at note synthesis (A2 input has no speaker info).
    """

    SPK_A = "SPK_A"
    SPK_B = "SPK_B"
    SPK_C = "SPK_C"
    SPK_D = "SPK_D"
    SPK_E = "SPK_E"
    UNKNOWN = "UNKNOWN"


class DiarisationState(StrEnum):
    """Diarisation state machine (spec section 2)."""

    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    COMPLETE = "complete"
    TAGGED = "tagged"
    FAILED = "failed"
    DISABLED = "disabled"


class DiarisationResult(BaseModel):
    session_id: UUID
    speaker_count: int = Field(..., ge=0)
    utterance_speaker_map: dict[int, str]  # sequence -> speaker_tag
    processing_time_ms: int
    model_name: str = "pyannote/speaker-diarization-3.1"
    state: DiarisationState = DiarisationState.NOT_STARTED


class NFRS4AuditResult(BaseModel):
    """NFR-S4 compliance audit result."""

    session_id: UUID
    voiceprints_found: int = Field(0, description="Must be 0")
    embeddings_persisted: int = Field(0, description="Must be 0")
    biometric_templates: int = Field(0, description="Must be 0")
    speaker_tags_session_scoped: bool = Field(True, description="Must be True")
    cross_session_linkage_possible: bool = Field(False, description="Must be False")
    compliant: bool
    audit_timestamp: datetime


class NonLinkabilityAssertion(BaseModel):
    """NFR-S4: Biometric non-linkability assertion."""

    session_a_id: UUID
    session_b_id: UUID
    tags_session_a: list[str]
    tags_session_b: list[str]
    overlap_count: int = Field(0, description="Must be 0 - tags are session-local")
    linkable: bool = Field(False, description="Must be False")
    assertion_passed: bool
