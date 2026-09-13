"""T07.4 - Pydantic schema validation tests."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from src.api.schemas.session import SessionCreate
from src.api.schemas.subject import SubjectCreate, SubjectUpdate


class TestSubjectValidation:
    """T07.4 - Pydantic schema rejects malformed subject payloads."""

    def test_valid_subject_create(self) -> None:
        s = SubjectCreate(name="Machine Learning", description="CS-229")
        assert s.name == "Machine Learning"
        assert s.description == "CS-229"

    def test_subject_create_without_description(self) -> None:
        s = SubjectCreate(name="ML")
        assert s.description is None

    def test_subject_create_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubjectCreate(name="")

    def test_subject_create_whitespace_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubjectCreate(name="   ")

    def test_subject_create_long_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubjectCreate(name="x" * 256)

    def test_subject_create_max_length_name(self) -> None:
        s = SubjectCreate(name="x" * 255)
        assert len(s.name) == 255

    def test_subject_create_long_description_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubjectCreate(name="Valid", description="x" * 2001)

    def test_subject_create_max_length_description(self) -> None:
        s = SubjectCreate(name="Valid", description="x" * 2000)
        assert len(s.description) == 2000  # type: ignore[arg-type]

    def test_subject_update_valid(self) -> None:
        s = SubjectUpdate(name="New Name", description="New desc")
        assert s.name == "New Name"

    def test_subject_update_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubjectUpdate(name="")

    def test_subject_update_long_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubjectUpdate(name="x" * 256)


class TestSessionValidation:
    """Session schema validation tests."""

    def test_valid_session_create(self) -> None:
        s = SessionCreate(subject_id=uuid.uuid4(), session_type="content")
        assert s.session_type == "content"

    def test_session_create_default_type(self) -> None:
        s = SessionCreate(subject_id=uuid.uuid4())
        assert s.session_type == "content"

    def test_session_create_syllabus_type(self) -> None:
        s = SessionCreate(subject_id=uuid.uuid4(), session_type="syllabus")
        assert s.session_type == "syllabus"

    def test_session_create_mixed_type(self) -> None:
        s = SessionCreate(subject_id=uuid.uuid4(), session_type="mixed")
        assert s.session_type == "mixed"

    def test_session_create_invalid_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionCreate(subject_id=uuid.uuid4(), session_type="invalid")

    def test_session_create_requires_subject_id(self) -> None:
        with pytest.raises(ValidationError):
            SessionCreate()  # type: ignore[call-arg]
