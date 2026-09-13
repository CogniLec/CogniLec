"""Subject partition provisioning - creates table partitions per subject."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.subject import Subject
from src.db.partitions.config import (
    HNSW_EF_CONSTRUCTION,
    HNSW_M,
    MAX_PROVISION_RETRIES,
    PARTITIONED_TABLES,
    VECTOR_TABLES,
)

logger = structlog.get_logger()


class PartitionProvisioner:
    """Provisions and deprovisions per-subject table partitions."""

    async def provision_subject(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        name: str,
        description: str | None = None,
    ) -> Subject:
        """Create subject + all partitions + HNSW indexes in one transaction.

        All DDL runs inside the caller's transaction. On deadlock, retries up
        to MAX_PROVISION_RETRIES times with a SAVEPOINT-rollback pattern.
        """
        subject = Subject(user_id=user_id, name=name, description=description)
        session.add(subject)
        await session.flush()

        subject_id = subject.id
        subject_hex = subject_id.hex[:8]
        subject_str = str(subject_id)

        for attempt in range(1, MAX_PROVISION_RETRIES + 1):
            try:
                await self._create_partitions(session, subject_id, subject_hex, subject_str)
                break
            except OperationalError as exc:
                if "deadlock" in str(exc).lower() and attempt < MAX_PROVISION_RETRIES:
                    logger.warning(
                        "provision_deadlock_retry",
                        subject_id=subject_str,
                        attempt=attempt,
                    )
                    await session.rollback()
                    await session.begin_nested()
                    continue
                raise

        await session.flush()
        logger.info(
            "subject_provisioned",
            subject_id=subject_str,
            user_id=str(user_id),
            name=name,
        )
        return subject

    async def _create_partitions(
        self,
        session: AsyncSession,
        subject_id: uuid.UUID,
        subject_hex: str,
        subject_str: str,
    ) -> None:
        """Create partitions and HNSW indexes for a subject."""
        for table in PARTITIONED_TABLES:
            partition_name = f"{table}_{subject_hex}"

            await session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} "
                    f"PARTITION OF {table} FOR VALUES IN ('{subject_str}')"
                )
            )

            if table in VECTOR_TABLES:
                index_name = f"idx_{partition_name}_embedding"
                await session.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON {partition_name} USING hnsw (embedding vector_cosine_ops) "
                        f"WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})"
                    )
                )

    async def deprovision_subject(
        self,
        session: AsyncSession,
        subject_id: uuid.UUID,
    ) -> None:
        """Drop all partitions + subject in one transaction."""
        subject_hex = subject_id.hex[:8]

        # note_assets is a single global (non-partitioned) table with a
        # composite FK into note_sections (migration f4a1b9c3d7e2). It isn't
        # touched by the per-subject partition drops below, so this
        # subject's rows must be removed explicitly first or they'd be
        # orphaned once note_sections' partition for this subject is gone.
        await session.execute(
            text("DELETE FROM note_assets WHERE subject_id = :sid"), {"sid": subject_id}
        )

        # Drop in reverse of creation order (note_provenance's partition has
        # an FK to note_sections' partition), and CASCADE since dropping a
        # partition removes only the FK constraint objects tied to it, not
        # rows in unpartitioned referencing tables (handled above).
        for table in reversed(PARTITIONED_TABLES):
            partition_name = f"{table}_{subject_hex}"
            await session.execute(text(f"DROP TABLE IF EXISTS {partition_name} CASCADE"))

        await session.execute(
            text("DELETE FROM subjects WHERE id = :sid"),
            {"sid": subject_id},
        )

        await session.flush()
        logger.info("subject_deprovisioned", subject_id=str(subject_id))

    async def subject_partitions_exist(
        self,
        session: AsyncSession,
        subject_id: uuid.UUID,
    ) -> bool:
        """Check if partitions exist for a subject."""
        subject_hex = subject_id.hex[:8]
        partition_name = f"utterances_{subject_hex}"

        result = await session.execute(
            text("SELECT EXISTS (  SELECT 1 FROM pg_class WHERE relname = :name)"),
            {"name": partition_name},
        )

        row = result.fetchone()
        return bool(row[0]) if row else False
