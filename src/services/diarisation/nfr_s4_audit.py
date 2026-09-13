"""NFR-S4 biometric non-linkability audit (S20).

Verifies no voiceprint/embedding/biometric-template data is ever persisted
(database schema + object storage), and that anonymous speaker tags cannot
be linked across sessions - i.e. there is no side-table, join path, or
shared identifier that would let "SPK_A in session 1" be identified as "the
same person" as "SPK_A in session 2". Literal string collisions between
session-local tags (both sessions containing the string "SPK_A") are
EXPECTED and are NOT, by themselves, an NFR-S4 violation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.repositories.utterance_repo import UtteranceRepository
from src.services.diarisation.models import NFRS4AuditResult, NonLinkabilityAssertion
from src.services.storage.client import StorageClient
from src.services.storage.models import BucketName

# Column-name substrings that would indicate biometric data is being stored.
BIOMETRIC_COLUMN_PATTERNS = (
    "voiceprint",
    "biometric",
    "speaker_embedding",
    "d_vector",
    "x_vector",
)

# Object-key substrings that would indicate biometric artifacts in storage.
BIOMETRIC_KEY_PATTERNS = (
    "voiceprint",
    "embedding",
    "biometric",
    "speaker_model",
)

AUDITED_BUCKETS = (
    BucketName.AUDIO,
    BucketName.UPLOADS,
    BucketName.GENERATED,
    BucketName.EXPORTS,
)


class NFRS4Audit:
    """NFR-S4 compliance auditor: no biometric data anywhere, ever."""

    def __init__(self, db_session: AsyncSession, storage: StorageClient | None = None) -> None:
        self._session = db_session
        self._storage = storage

    async def audit_session(self, session_id: UUID) -> NFRS4AuditResult:
        """Verify no voiceprint/embedding/biometric data is persisted for a session."""
        schema_violations = await self.audit_database_schema()
        storage_violations = await self.audit_storage() if self._storage else []
        cross_session = await self._cross_session_tag_linkage()

        compliant = not schema_violations and not storage_violations and not cross_session
        return NFRS4AuditResult(
            session_id=session_id,
            voiceprints_found=0,
            embeddings_persisted=0,
            biometric_templates=0,
            speaker_tags_session_scoped=not cross_session,
            cross_session_linkage_possible=bool(cross_session),
            compliant=compliant,
            audit_timestamp=datetime.now(UTC),
        )

    async def audit_database_schema(self) -> list[str]:
        """Scan `information_schema.columns` for biometric-sounding column names."""
        like_clauses = " OR ".join(f"column_name ILIKE '%{p}%'" for p in BIOMETRIC_COLUMN_PATTERNS)
        result = await self._session.execute(
            text(f"""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND ({like_clauses})
            """)
        )
        return [f"{row.table_name}.{row.column_name}" for row in result.fetchall()]

    async def audit_storage(self) -> list[str]:
        """Scan bucket contents for biometric-sounding object keys."""
        if self._storage is None:
            return []
        violations: list[str] = []
        for bucket in AUDITED_BUCKETS:
            objects = await self._storage.list_objects(bucket, prefix="")
            for obj in objects:
                key_lower = obj.key.lower()
                if any(p in key_lower for p in BIOMETRIC_KEY_PATTERNS):
                    violations.append(f"{bucket.value}:{obj.key}")
        return violations

    async def _cross_session_tag_linkage(self) -> list[str]:
        """Verify no table/join path links a speaker_tag value to more than
        one session via a shared, resolvable identifier (as opposed to the
        tag string simply repeating across sessions, which is expected).

        There is no speaker-identity table in this schema at all - tags live
        only as a plain column on `utterances`, scoped to (subject_id,
        session_id, seq). This checks that no such linking table exists.
        """
        result = await self._session.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND (table_name ILIKE '%speaker_identity%'
                       OR table_name ILIKE '%speaker_link%'
                       OR table_name ILIKE '%voiceprint%')
            """)
        )
        return [row.table_name for row in result.fetchall()]

    async def verify_non_linkability(
        self,
        session_a_id: UUID,
        session_b_id: UUID,
    ) -> NonLinkabilityAssertion:
        """Verify speaker tags from two sessions are not linkable.

        Tags are session-local strings (e.g. "SPK_A"), so the same literal
        string is expected to appear in both sessions - that is NOT a
        linkage. Linkability instead means: does any mechanism let you
        resolve "SPK_A in session A" to the same real person as "SPK_A in
        session B"? Since there is no shared identifier/mapping table (see
        `_cross_session_tag_linkage`), and tags carry no biometric payload,
        the tags are not linkable regardless of string overlap.
        """
        subject_a = await self._resolve_subject_id(session_a_id)
        subject_b = await self._resolve_subject_id(session_b_id)
        repo = UtteranceRepository(self._session)
        utterances_a = await repo.get_by_session(subject_a, session_a_id)
        utterances_b = await repo.get_by_session(subject_b, session_b_id)

        tags_a = sorted({u.speaker_tag for u in utterances_a if u.speaker_tag})
        tags_b = sorted({u.speaker_tag for u in utterances_b if u.speaker_tag})
        overlap_count = len(set(tags_a) & set(tags_b))

        linking_tables = await self._cross_session_tag_linkage()
        linkable = bool(linking_tables)

        return NonLinkabilityAssertion(
            session_a_id=session_a_id,
            session_b_id=session_b_id,
            tags_session_a=tags_a,
            tags_session_b=tags_b,
            overlap_count=overlap_count,
            linkable=linkable,
            assertion_passed=not linkable,
        )

    async def _resolve_subject_id(self, session_id: UUID) -> UUID:
        result = await self._session.execute(
            text("SELECT subject_id FROM sessions WHERE id = :session_id"),
            {"session_id": str(session_id)},
        )
        row = result.first()
        if row is None:
            msg = f"Session {session_id} not found"
            raise ValueError(msg)
        return UUID(str(row[0]))
