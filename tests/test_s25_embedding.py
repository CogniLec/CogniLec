"""Tests for S25 - embedding service & version governance (T25.2, T25.3, T25.6)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.session import Session
from src.db.models.user import User
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.utterance_repo import UtteranceRepository
from src.ml.embedding.client import EmbeddingClient
from src.ml.embedding.versioning import DimensionError, get_active_version, stamp_version

pytestmark = pytest.mark.integration


async def _subject_and_session(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@x.com", hashed_password="h", is_active=True)
    db.add(user)
    await db.flush()
    provisioner = PartitionProvisioner()
    subject = await provisioner.provision_subject(
        db, user.id, name=f"S25 Subject {uuid.uuid4().hex[:8]}"
    )
    session_obj = Session(subject_id=subject.id, session_type="content")
    db.add(session_obj)
    await db.flush()
    return subject.id, session_obj.id


class TestVersionRegistry:
    def test_get_active_version(self) -> None:
        info = get_active_version()
        assert info.key == "qwen3-0.6b-v1"
        assert info.dim == 1024
        assert info.status == "active"

    def test_stamp_version(self) -> None:
        row = {"text": "hello"}
        stamp_version(row, "qwen3-0.6b-v1")
        assert row["embed_model_ver"] == "qwen3-0.6b-v1"


class TestT252NotNullEmbedModelVer:
    async def test_bulk_insert_rejects_missing_embed_model_ver(
        self, db_session: AsyncSession
    ) -> None:
        """T25.2: an utterance dict without embed_model_ver is rejected."""
        subject_id, session_id = await _subject_and_session(db_session)
        repo = UtteranceRepository(db_session)
        bad_row = {
            "session_id": session_id,
            "seq": 0,
            "start_ms": 0,
            "end_ms": 100,
            "text": "no version",
            "words": [],
        }
        with pytest.raises(Exception):  # NOT NULL violation surfaces as a DBAPIError
            await repo.bulk_insert(subject_id, [bad_row])


class TestT253ActiveVersionFilter:
    async def test_vector_query_filters_active_version(self, db_session: AsyncSession) -> None:
        """T25.3: two versions present; querying the active one excludes the deprecated one."""
        subject_id, session_id = await _subject_and_session(db_session)
        repo = UtteranceRepository(db_session)
        await repo.bulk_insert(
            subject_id,
            [
                {
                    "session_id": session_id,
                    "seq": 0,
                    "start_ms": 0,
                    "end_ms": 100,
                    "text": "old",
                    "words": [],
                    "asr_confidence": None,
                    "speaker_tag": None,
                    "embed_model_ver": "old-v1",
                },
                {
                    "session_id": session_id,
                    "seq": 1,
                    "start_ms": 100,
                    "end_ms": 200,
                    "text": "new",
                    "words": [],
                    "asr_confidence": None,
                    "speaker_tag": None,
                    "embed_model_ver": "qwen3-0.6b-v1",
                },
            ],
        )
        rows = await repo.get_by_embed_version(subject_id, "old-v1")
        assert len(rows) == 1
        assert rows[0]["text"] == "old"

        rows_active = await repo.get_by_embed_version(subject_id, "qwen3-0.6b-v1")
        assert len(rows_active) == 1
        assert rows_active[0]["text"] == "new"


class TestT256InstructionPrefix:
    async def test_clustering_prefix_prepended(self) -> None:
        """T25.6: clustering task mode prepends the clustering instruction prefix."""
        client = EmbeddingClient(fallback_local=True)
        captured: list[str] = []

        async def fake_tei(texts: list[str]) -> list[list[float]]:
            captured.extend(texts)
            return [[0.0] * 1024 for _ in texts]

        client._embed_via_tei = fake_tei  # type: ignore[method-assign]
        await client.embed(["gradient descent", "neural network"], task_mode="clustering")

        assert captured == [
            "Cluster semantically similar content: gradient descent",
            "Cluster semantically similar content: neural network",
        ]

    async def test_dimension_mismatch_raises(self) -> None:
        client = EmbeddingClient(fallback_local=True)

        async def bad_tei(texts: list[str]) -> list[list[float]]:
            return [[0.0] * 5 for _ in texts]

        client._embed_via_tei = bad_tei  # type: ignore[method-assign]
        with pytest.raises(DimensionError):
            await client.embed(["x"])


class TestBatching:
    """Regression: `embed()` used to send every text in ONE TEI request, no
    batching at all -- confirmed live, repeatedly: this 413s on any real
    session's full utterance/note set, forcing every call onto the local
    CPU fallback, which then OOM-killed the 4GB asr-worker container
    outright (silently -- a container OOM kill doesn't let Python's own
    exception handlers run), leaving real sessions permanently stuck.
    """

    async def test_texts_are_sent_in_batches_not_one_request(self) -> None:
        client = EmbeddingClient(fallback_local=True, batch_size=2)
        call_sizes: list[int] = []

        async def fake_tei(texts: list[str]) -> list[list[float]]:
            call_sizes.append(len(texts))
            return [[0.0] * 1024 for _ in texts]

        client._embed_via_tei = fake_tei  # type: ignore[method-assign]
        result = await client.embed([f"t{i}" for i in range(5)])

        assert call_sizes == [2, 2, 1]
        assert len(result) == 5

    async def test_one_batch_falling_back_to_local_does_not_affect_others(self) -> None:
        client = EmbeddingClient(fallback_local=True, batch_size=2)
        tei_call_count = 0

        async def flaky_tei(texts: list[str]) -> list[list[float]]:
            nonlocal tei_call_count
            tei_call_count += 1
            if tei_call_count == 2:
                raise httpx.HTTPError("simulated 413")
            return [[0.0] * 1024 for _ in texts]

        client._embed_via_tei = flaky_tei  # type: ignore[method-assign]
        client._embed_local = lambda texts: [[1.0] * 1024 for _ in texts]  # type: ignore[method-assign]

        result = await client.embed([f"t{i}" for i in range(4)])
        assert len(result) == 4
        assert result[0] == [0.0] * 1024  # first batch: real TEI call
        assert result[2] == [1.0] * 1024  # second batch: fell back to local
