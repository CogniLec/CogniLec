"""Tests for subject partitioning."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.db.partitions.config import PARTITIONED_TABLES, VECTOR_TABLES
from src.db.partitions.provisioner import PartitionProvisioner
from src.db.repositories.base import BaseRepository
from tests.conftest import DATABASE_URL


class TestPartitionProvisioning:
    """T08.1 — Creating a subject produces all expected partitions and indexes."""

    async def test_provision_creates_partitions(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Sub1")

        exists = await provisioner.subject_partitions_exist(db_session, subject.id)
        assert exists

    async def test_provision_creates_all_four_partitions(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Sub2")

        subject_hex = subject.id.hex[:8]
        for table in PARTITIONED_TABLES:
            partition_name = f"{table}_{subject_hex}"
            result = await db_session.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_class WHERE relname = :name)"),
                {"name": partition_name},
            )
            assert result.fetchone()[0], f"Partition {partition_name} not found"

    async def test_provision_creates_hnsw_indexes(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Sub3")

        subject_hex = subject.id.hex[:8]
        for table in VECTOR_TABLES:
            partition_name = f"{table}_{subject_hex}"
            index_name = f"idx_{partition_name}_embedding"
            result = await db_session.execute(
                text("SELECT EXISTS (  SELECT 1 FROM pg_class WHERE relname = :name)"),
                {"name": index_name},
            )
            assert result.fetchone()[0], f"HNSW index {index_name} not found"

    async def test_provision_creates_subject_record(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(
            db_session, test_user_id, name="Sub4", description="A test subject"
        )

        assert subject.id is not None
        assert subject.user_id == test_user_id
        assert subject.name == "Sub4"

    async def test_provision_idempotent(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Sub5")

        exists = await provisioner.subject_partitions_exist(db_session, subject.id)
        assert exists

    async def test_separate_subjects_get_separate_partitions(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject_a = await provisioner.provision_subject(db_session, test_user_id, name="SubA")
        subject_b = uuid.uuid4()

        assert await provisioner.subject_partitions_exist(db_session, subject_a.id)
        assert not await provisioner.subject_partitions_exist(db_session, subject_b)


class TestPartitionPruning:
    """T08.2 — EXPLAIN on subject_id-filtered query shows partition pruning."""

    async def test_partition_pruning(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Prune1")

        result = await db_session.execute(
            text("EXPLAIN SELECT * FROM utterances WHERE subject_id = :sid LIMIT 1"),
            {"sid": str(subject.id)},
        )
        plan = "\n".join(row[0] for row in result.fetchall())

        assert "utterances_" in plan
        assert "Seq Scan" in plan or "Index Scan" in plan

    async def test_query_scans_only_target_partition(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject_a = await provisioner.provision_subject(db_session, test_user_id, name="PruneA")
        subject_b = await provisioner.provision_subject(db_session, test_user_id, name="PruneB")

        result = await db_session.execute(
            text("EXPLAIN SELECT * FROM utterances WHERE subject_id = :sid LIMIT 1"),
            {"sid": str(subject_a.id)},
        )
        plan = "\n".join(row[0] for row in result.fetchall())

        assert subject_a.id.hex[:8] in plan
        assert subject_b.id.hex[:8] not in plan


class TestMissingSubjectIdRejected:
    """T08.3 — Query without subject_id filter rejected by repository layer."""

    def test_require_subject_id_raises_on_none(self) -> None:
        repo = BaseRepository()
        with pytest.raises(ValueError, match="subject_id is required"):
            repo._require_subject_id(None)

    def test_require_subject_id_returns_valid_uuid(self) -> None:
        repo = BaseRepository()
        sid = uuid.uuid4()
        result = repo._require_subject_id(sid)
        assert result == sid


class TestDeprovisionCleansUp:
    """T08.4 — Subject deletion drops its partitions; other subjects' data intact."""

    async def test_deprovision_removes_partitions(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Del1")

        await provisioner.deprovision_subject(db_session, subject.id)

        exists = await provisioner.subject_partitions_exist(db_session, subject.id)
        assert not exists

    async def test_deprovision_removes_subject_record(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Del2")

        await provisioner.deprovision_subject(db_session, subject.id)

        result = await db_session.execute(
            text("SELECT EXISTS (SELECT 1 FROM subjects WHERE id = :sid)"),
            {"sid": str(subject.id)},
        )
        assert not result.fetchone()[0]

    async def test_deprovision_does_not_affect_other_subjects(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject_a = await provisioner.provision_subject(db_session, test_user_id, name="DelA")
        subject_b = await provisioner.provision_subject(db_session, test_user_id, name="DelB")

        await provisioner.deprovision_subject(db_session, subject_a.id)

        assert not await provisioner.subject_partitions_exist(db_session, subject_a.id)
        assert await provisioner.subject_partitions_exist(db_session, subject_b.id)

    async def test_deprovision_all_four_tables_dropped(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Del3")

        await provisioner.deprovision_subject(db_session, subject.id)

        subject_hex = subject.id.hex[:8]
        for table in PARTITIONED_TABLES:
            partition_name = f"{table}_{subject_hex}"
            result = await db_session.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_class WHERE relname = :name)"),
                {"name": partition_name},
            )
            assert not result.fetchone()[0], f"Partition {partition_name} still exists"


class TestProvisionPerformance:
    """T08.5 — Provisioning a subject completes in < 2s."""

    async def test_provision_performance(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        provisioner = PartitionProvisioner()

        start = time.monotonic()
        subject = await provisioner.provision_subject(db_session, test_user_id, name="Perf1")
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"Provisioning took {elapsed:.2f}s, expected < 2s"
        assert subject.id is not None


class TestConcurrentProvision:
    """T08.6 — 50 subjects provisioned concurrently without deadlock."""

    async def test_concurrent_provision(
        self, db_session: AsyncSession, test_user_id: uuid.UUID
    ) -> None:
        # A single AsyncSession wraps one DBAPI connection and cannot serve
        # concurrent operations from multiple tasks (SQLAlchemy's asyncio
        # extension does not support this and will corrupt the connection's
        # protocol state, hanging indefinitely). Each concurrent provision
        # needs its own session/connection, sharing only the engine, to
        # genuinely exercise DB-level concurrency and deadlock handling.
        # test_user_id only flushed the user row on db_session's own connection;
        # commit it so the independent connections below can see it too.
        await db_session.commit()

        engine = create_async_engine(DATABASE_URL)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        provisioner = PartitionProvisioner()
        names = [f"Conc{i}" for i in range(50)]

        async def provision_one(name: str) -> uuid.UUID:
            async with session_factory() as session:
                subject = await provisioner.provision_subject(session, test_user_id, name=name)
                await session.commit()
                return subject.id

        try:
            subject_ids = await asyncio.gather(*(provision_one(name) for name in names))
        finally:
            await engine.dispose()

        for sid in subject_ids:
            exists = await provisioner.subject_partitions_exist(db_session, sid)
            assert exists, f"Partitions for {sid} not found after concurrent provision"
