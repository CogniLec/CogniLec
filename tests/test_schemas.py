"""T07.4 — Pydantic schemas reject malformed payloads."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from src.api.schemas.session import SessionCreate
from src.api.schemas.subject import SubjectCreate

pytestmark = pytest.mark.unit


class TestSubjectValidation:
    def test_subject_validation(self) -> None:
        with pytest.raises(ValidationError):
            SubjectCreate(name="")

        with pytest.raises(ValidationError):
            SubjectCreate(name="x" * 256)

        with pytest.raises(ValidationError):
            SubjectCreate(name="Math", description="x" * 2001)

        subject = SubjectCreate(name="Math", description="Intro to calculus")
        assert subject.name == "Math"
        assert subject.description == "Intro to calculus"

    def test_subject_description_optional(self) -> None:
        subject = SubjectCreate(name="Math")
        assert subject.description is None


class TestSessionValidation:
    def test_session_type_must_be_declared_enum(self) -> None:
        with pytest.raises(ValidationError):
            SessionCreate(subject_id=uuid4(), session_type="not_a_real_type")

    def test_session_type_defaults_to_content(self) -> None:
        session = SessionCreate(subject_id=uuid4())
        assert session.session_type == "content"
