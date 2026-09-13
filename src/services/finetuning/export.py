"""S65 — training dataset export: corrections -> versioned, DVC-tracked JSONL.

Two invariants T65.3/T65.6 require:
  - no PII in the exported record (user_id is dropped, never included)
  - no cross-user leakage: a correction is only exported if its owner
    consented (`consent_for_training`), unless the caller explicitly asks
    for a single user's own corrections (their own data, not a leak).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.correction import Correction

_PII_FIELDS = {"user_id", "email"}


def _scrub(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _PII_FIELDS}


@dataclass(frozen=True)
class ExportedExample:
    correction_type: str
    subject_id: str | None
    source_id: str | None
    original_value: dict[str, Any]
    corrected_value: dict[str, Any]
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _scrub(
            {
                "correction_type": self.correction_type,
                "subject_id": self.subject_id,
                "source_id": self.source_id,
                "original_value": self.original_value,
                "corrected_value": self.corrected_value,
                "context": self.context,
            }
        )


async def export_training_dataset(
    session: AsyncSession,
    *,
    correction_types: list[str] | None = None,
    require_consent: bool = True,
    owner_user_id: uuid.UUID | None = None,
) -> list[ExportedExample]:
    """Build the training-ready example list.

    `require_consent=True` (the default) includes only rows whose author
    opted in via `consent_for_training`. Passing `owner_user_id` instead
    scopes the export to one user's own corrections regardless of the
    consent flag - that's the user exporting their own data, not a leak
    to anyone else (T65.6).
    """
    stmt = select(Correction)
    if correction_types:
        stmt = stmt.where(Correction.correction_type.in_(correction_types))
    if owner_user_id is not None:
        stmt = stmt.where(Correction.user_id == owner_user_id)
    elif require_consent:
        stmt = stmt.where(Correction.consent_for_training.is_(True))

    rows = (await session.execute(stmt)).scalars().all()
    return [
        ExportedExample(
            correction_type=row.correction_type,
            subject_id=str(row.subject_id) if row.subject_id else None,
            source_id=str(row.source_id) if row.source_id else None,
            original_value=row.original_value,
            corrected_value=row.corrected_value,
            context=row.context,
        )
        for row in rows
    ]


def write_dataset_jsonl(examples: list[ExportedExample], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for example in examples:
            f.write(json.dumps(example.to_dict()) + "\n")
    return out_path


class DVCError(Exception):
    """Raised when a `dvc` CLI invocation fails."""


def dvc_add(path: Path, repo_root: Path) -> Path:
    """Track `path` with DVC, producing `path.dvc` (versioned via git).

    Runs `dvc add` inside `repo_root`. Requires a `dvc init`-ed repo; callers
    that need reproducibility should commit the resulting `.dvc` pointer
    file to git alongside their code change (T65.4).
    """
    dvc_bin = str(Path(sys.executable).with_name("dvc")) if shutil.which("dvc") is None else "dvc"
    result = subprocess.run(
        [dvc_bin, "add", str(path.relative_to(repo_root))],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"dvc add failed: {result.stderr}"
        raise DVCError(msg)
    return path.with_suffix(path.suffix + ".dvc")


def export_and_version_dataset(
    session_examples: list[ExportedExample],
    dataset_name: str,
    version: str,
    datasets_dir: Path,
    repo_root: Path,
    *,
    track_with_dvc: bool = True,
) -> Path:
    """S65 export flow: write a versioned JSONL, optionally DVC-track it.

    File naming embeds `version` so successive exports never clobber each
    other - `datasets/<dataset_name>/<version>.jsonl` - which is what makes
    the export reproducible (T65.4): re-running the same query against the
    same `corrections` state and writing to the same version path yields a
    byte-identical file.
    """
    out_path = datasets_dir / dataset_name / f"{version}.jsonl"
    write_dataset_jsonl(session_examples, out_path)
    if track_with_dvc:
        dvc_add(out_path, repo_root)
    return out_path
