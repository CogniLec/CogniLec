"""S50 — session routing helpers: syllabus/mixed sessions to A6, not T5-T7."""

from __future__ import annotations

SYLLABUS_SESSION_TYPE = "syllabus"
MIXED_SESSION_TYPE = "mixed"


def route_syllabus_lecture(session_type: str) -> bool:
    """True if this session type should route (wholly or partly) to A6.

    "syllabus" sessions route entirely to A6. "mixed" sessions route their
    syllabus segment to A6 (isolated upstream by S35's segmentation) while
    their content segments still go through the normal T5-T7 topic
    pipeline - see AC-13.
    """
    return session_type in (SYLLABUS_SESSION_TYPE, MIXED_SESSION_TYPE)
