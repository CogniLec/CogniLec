"""Tests for S65 - correction capture & training data pipeline (T65.1-T65.6).

T65.1-T65.3/T65.5/T65.6 run against the real Postgres test DB (`db_session`
fixture) - real inserts, a real immutability rule, a real export query.
T65.4 (DVC-reproducible export) invokes the real `dvc` CLI against a
scratch `dvc init`-ed directory; the invocation is real, not mocked.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.partitions.provisioner import PartitionProvisioner
from src.services.finetuning import corrections as capture
from src.services.finetuning.export import (
    export_and_version_dataset,
    export_training_dataset,
)


async def _make_subject(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    subject = await PartitionProvisioner().provision_subject(session, user_id, name="S65 Subject")
    return subject.id


async def _make_utterance(session: AsyncSession, subject_id: uuid.UUID) -> uuid.UUID:
    session_row_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO sessions (id, subject_id, session_type, status, notes_ready, retry_count) "
            "VALUES (:id, :subject_id, 'content', 'complete', false, 0)"
        ),
        {"id": str(session_row_id), "subject_id": str(subject_id)},
    )
    utterance_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO utterances "
            "(id, subject_id, session_id, seq, start_ms, end_ms, text, embed_model_ver, is_relevant) "
            "VALUES (:id, :subject_id, :session_id, 1, 0, 1000, "
            "'some lecture text', 'qwen3-0.6b-v1', true)"
        ),
        {"id": str(utterance_id), "subject_id": str(subject_id), "session_id": str(session_row_id)},
    )
    await session.flush()
    return utterance_id


@pytest.mark.asyncio
async def test_t65_1_all_six_correction_types_captured(db_session, test_user_id):
    subject_id = await _make_subject(db_session, test_user_id)
    utterance_id = await _make_utterance(db_session, subject_id)

    a1 = await capture.capture_a1_relevance_override(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        utterance_id=utterance_id,
        original_is_relevant=True,
        corrected_is_relevant=False,
        utterance_text="some lecture text",
        topic_label="thermodynamics",
        outlier_score=0.2,
    )
    assert a1.correction_type == "a1_relevance_override"
    assert a1.original_value == {"is_relevant": True}
    assert a1.corrected_value == {"is_relevant": False}

    topic_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO topics (id, subject_id, centroid, label) "
            "VALUES (:id, :subject_id, :centroid, 'auto label')"
        ),
        {"id": str(topic_id), "subject_id": str(subject_id), "centroid": str([0.0] * 1024)},
    )
    label_edit = await capture.capture_topic_label_edit(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        topic_id=topic_id,
        original_label="auto label",
        corrected_label="Heat Transfer",
        keywords=["heat", "transfer"],
    )
    assert label_edit.correction_type == "topic_label_edit"
    assert label_edit.corrected_value["label"] == "Heat Transfer"

    split_merge = await capture.capture_topic_split_merge(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        original_topic_ids=[topic_id],
        resulting_topic_ids=[uuid.uuid4(), uuid.uuid4()],
        operation="split",
    )
    assert split_merge.context["operation"] == "split"

    syllabus_item_id = uuid.uuid4()
    alignment = await capture.capture_syllabus_alignment_correction(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        syllabus_item_id=syllabus_item_id,
        original_topic_id=None,
        corrected_topic_id=topic_id,
        syllabus_item_text="Chapter 3: Thermodynamics",
    )
    assert alignment.correction_type == "syllabus_alignment"
    assert alignment.corrected_value["topic_id"] == str(topic_id)

    image_rejection = await capture.capture_image_rejection(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        image_id=uuid.uuid4(),
        concept_description="a piston diagram",
        rejection_reason="wrong_style",
    )
    assert image_rejection.corrected_value["accepted"] is False

    note_section_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO note_sections (id, subject_id, heading, body_md, ordinal) "
            "VALUES (:id, :subject_id, 'Intro', 'original body', 0)"
        ),
        {"id": str(note_section_id), "subject_id": str(subject_id)},
    )
    note_edit = await capture.capture_note_edit(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        note_section_id=note_section_id,
        original_body_md="original body",
        corrected_body_md="corrected body with more detail",
        heading="Intro",
    )
    assert note_edit.correction_type == "note_edit"

    row = await db_session.execute(
        text("SELECT body_md FROM note_sections WHERE id = :id"), {"id": str(note_section_id)}
    )
    assert row.scalar_one() == "corrected body with more detail"

    all_types = {
        c.correction_type
        for c in (a1, label_edit, split_merge, alignment, image_rejection, note_edit)
    }
    assert all_types == {
        "a1_relevance_override",
        "topic_label_edit",
        "topic_split_merge",
        "syllabus_alignment",
        "image_rejection",
        "note_edit",
    }


@pytest.mark.asyncio
async def test_t65_2_corrections_are_immutable_append_only(db_session, test_user_id):
    subject_id = await _make_subject(db_session, test_user_id)
    utterance_id = await _make_utterance(db_session, subject_id)
    correction = await capture.capture_a1_relevance_override(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        utterance_id=utterance_id,
        original_is_relevant=True,
        corrected_is_relevant=False,
        utterance_text="x",
        topic_label="y",
        outlier_score=None,
    )
    await db_session.commit()

    await db_session.execute(
        text("UPDATE corrections SET corrected_value = '{\"is_relevant\": true}' WHERE id = :id"),
        {"id": str(correction.id)},
    )
    await db_session.execute(
        text("DELETE FROM corrections WHERE id = :id"), {"id": str(correction.id)}
    )
    await db_session.commit()

    row = await db_session.execute(
        text("SELECT corrected_value FROM corrections WHERE id = :id"), {"id": str(correction.id)}
    )
    remaining = row.fetchone()
    assert remaining is not None, "DELETE must be a no-op (append-only)"
    assert remaining[0] == {"is_relevant": False}, "UPDATE must be a no-op (immutable)"


@pytest.mark.asyncio
async def test_t65_3_export_scrubs_pii_and_excludes_non_consenting_rows(db_session, test_user_id):
    subject_id = await _make_subject(db_session, test_user_id)
    utterance_id = await _make_utterance(db_session, subject_id)
    await capture.capture_a1_relevance_override(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        utterance_id=utterance_id,
        original_is_relevant=True,
        corrected_is_relevant=False,
        utterance_text="x",
        topic_label="y",
        outlier_score=None,
        consent_for_training=True,
    )
    other_user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, is_active) "
            "VALUES (:id, :email, 'x', true)"
        ),
        {"id": str(other_user_id), "email": f"other_{other_user_id.hex[:8]}@example.com"},
    )
    await capture.capture_a1_relevance_override(
        db_session,
        subject_id=subject_id,
        user_id=other_user_id,
        utterance_id=utterance_id,
        original_is_relevant=True,
        corrected_is_relevant=False,
        utterance_text="z",
        topic_label="y",
        outlier_score=None,
        consent_for_training=False,
    )
    await db_session.flush()

    exported = await export_training_dataset(db_session, require_consent=True)
    assert len(exported) == 1
    record = exported[0].to_dict()
    assert "user_id" not in record
    assert record["context"]["utterance_text"] == "x"


@pytest.mark.asyncio
async def test_t65_6_export_scoped_to_owner_never_leaks_others(db_session, test_user_id):
    subject_id = await _make_subject(db_session, test_user_id)
    utterance_id = await _make_utterance(db_session, subject_id)
    await capture.capture_a1_relevance_override(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        utterance_id=utterance_id,
        original_is_relevant=True,
        corrected_is_relevant=False,
        utterance_text="mine",
        topic_label="y",
        outlier_score=None,
        consent_for_training=False,
    )
    other_user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, is_active) "
            "VALUES (:id, :email, 'x', true)"
        ),
        {"id": str(other_user_id), "email": f"other2_{other_user_id.hex[:8]}@example.com"},
    )
    await capture.capture_a1_relevance_override(
        db_session,
        subject_id=subject_id,
        user_id=other_user_id,
        utterance_id=utterance_id,
        original_is_relevant=True,
        corrected_is_relevant=False,
        utterance_text="not mine",
        topic_label="y",
        outlier_score=None,
        consent_for_training=False,
    )
    await db_session.flush()

    exported = await export_training_dataset(db_session, owner_user_id=test_user_id)
    assert len(exported) == 1
    assert exported[0].context["utterance_text"] == "mine"


@pytest.mark.asyncio
async def test_t65_5_correction_immediately_visible_in_live_row(db_session, test_user_id):
    subject_id = await _make_subject(db_session, test_user_id)
    utterance_id = await _make_utterance(db_session, subject_id)
    await capture.capture_a1_relevance_override(
        db_session,
        subject_id=subject_id,
        user_id=test_user_id,
        utterance_id=utterance_id,
        original_is_relevant=True,
        corrected_is_relevant=False,
        utterance_text="x",
        topic_label="y",
        outlier_score=None,
    )
    row = await db_session.execute(
        text("SELECT is_relevant, filter_reason FROM utterances WHERE id = :id"),
        {"id": str(utterance_id)},
    )
    is_relevant, filter_reason = row.fetchone()
    assert is_relevant is False
    assert filter_reason == "user_override"


def test_t65_4_export_is_dvc_reproducible_and_versioned(tmp_path: Path):
    from src.services.finetuning.export import ExportedExample

    dvc_bin = str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "dvc")
    if not Path(dvc_bin).exists():
        pytest.skip(
            "dvc is not installed by default (gap #22: scoped out of the "
            "default dev install into the 'finetuning-ops' extra to avoid "
            "pulling in its copyleft-licensed transitive dependencies -- "
            "install with `uv sync --extra dev --extra finetuning-ops` to "
            "exercise this test)"
        )

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run([dvc_bin, "init", "-q"], cwd=repo_root, check=True)

    examples = [
        ExportedExample(
            correction_type="a1_relevance_override",
            subject_id=str(uuid.uuid4()),
            source_id=None,
            original_value={"is_relevant": True},
            corrected_value={"is_relevant": False},
            context={"utterance_text": "hello"},
        )
    ]
    out_path = export_and_version_dataset(
        examples,
        dataset_name="a1_relevance",
        version="v1",
        datasets_dir=repo_root / "datasets",
        repo_root=repo_root,
        track_with_dvc=False,
    )
    assert out_path.exists()

    dvc_pointer = repo_root / "datasets" / "a1_relevance" / "v1.jsonl.dvc"
    result = subprocess.run(
        [dvc_bin, "add", str(out_path.relative_to(repo_root))],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert dvc_pointer.exists()

    lines = out_path.read_text().splitlines()
    assert len(lines) == 1
    import json

    record = json.loads(lines[0])
    assert record["context"]["utterance_text"] == "hello"
