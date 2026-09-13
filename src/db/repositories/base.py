"""Base repository with common guards for partitioned queries."""

from __future__ import annotations

import uuid


class BaseRepository:
    """Base class providing common query guards for partitioned tables."""

    def _require_subject_id(self, subject_id: uuid.UUID | None) -> uuid.UUID:
        """Reject queries without subject_id to enforce partition pruning.

        The PostgreSQL query planner can only prune partitions when
        subject_id is a leading filter condition. Queries without it
        would scan all partitions, defeating the purpose of partitioning.
        """
        if subject_id is None:
            msg = "subject_id is required for partitioned queries"
            raise ValueError(msg)
        return subject_id
