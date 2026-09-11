# ADR-005: Subject Partitioning via pg_partman

## Status
Accepted

## Context
Subjects are isolated namespaces (FR-6.5). Data grows per subject:
- utterances: ~31k per 60-min session
- segments, note_sections, note_provenance: proportional
- Must query only one subject at a time (enforced)
- Partition pruning essential for performance

## Decision
pg_partman with LIST partitioning on subject_id:
- All large tables: PARTITION BY LIST (subject_id)
- subject_id leads primary key: (subject_id, id)
- Per-partition HNSW indexes for vector search
- Provisioning: single transaction creates subject + partitions + indexes
- Deprovisioning: drop partitions on subject delete
- pg_partman manages maintenance (detach old, create new)

## Consequences
- Query planner enforces isolation (partition pruning)
- Repository layer rejects queries without subject_id filter
- Provisioning < 2s per subject
- 50 concurrent subjects no deadlock

## Follow-up
- S08: Partitioning machinery
- S09: Utterances/segments schema
- S10: Notes/provenance schema
