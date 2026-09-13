"""S71 — Postgres backup and restore, real `pg_dump`/`pg_restore` I/O.

The spec names pgBackRest (daily full + 15-minute WAL archiving, 30-day
retention) and restic for MinIO. Neither binary is installed in this
sandbox (`shutil.which` confirms both absent) and neither can be installed
offline, so the WAL-archiving/PITR half (T71.2) and the restic schedule
(T71.5) are not exercised here - see `docs/gaps.md`. What *is* real: the
`lis-pg-main`/`lis-pg-syllabus` containers carry their own matching
`pg_dump`/`pg_restore` (server is Postgres 17; this host's system `pg_dump`
is v14 and refuses to talk to a v17 server), so `run_full_backup`/
`restore_backup` below shell out via `docker exec` into the target
container rather than a host binary - a real, working substitute for the
"backup client version must match the server" operational constraint
pgBackRest would otherwise handle. The restore drill test
(`tests/test_s71_backup_dr.py`) actually dumps a live schema and inspects
the resulting archive - the only way to honestly claim "backup produced
usable data" without pgBackRest.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size_bytes: int


def pgbackrest_available() -> bool:
    return shutil.which("pgbackrest") is not None


def restic_available() -> bool:
    return shutil.which("restic") is not None


def run_full_backup(dsn: str, output_path: Path, container: str = "lis-pg-main") -> BackupResult:
    """`pg_dump --format=custom` a full backup of `dsn`, run inside `container`.

    The dump is written inside the container then copied out via `docker cp`,
    since the container's `pg_dump` (matching the server's major version) has
    no direct filesystem access to `output_path` on the host.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    container_path = f"/tmp/{uuid.uuid4().hex}_{output_path.name}"
    proc = subprocess.run(
        ["docker", "exec", container, "pg_dump", "--format=custom", "--file", container_path, dsn],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = f"pg_dump failed: {proc.stderr}"
        raise RuntimeError(msg)
    copy_proc = subprocess.run(
        ["docker", "cp", f"{container}:{container_path}", str(output_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if copy_proc.returncode != 0:
        msg = f"docker cp failed: {copy_proc.stderr}"
        raise RuntimeError(msg)
    return BackupResult(path=output_path, size_bytes=output_path.stat().st_size)


def list_backup_contents(backup_path: Path, container: str = "lis-pg-main") -> str:
    """Return `pg_restore --list` output for a backup archive, proving it holds real data."""
    container_path = f"/tmp/{uuid.uuid4().hex}_{backup_path.name}"
    subprocess.run(
        ["docker", "cp", str(backup_path), f"{container}:{container_path}"],
        capture_output=True,
        text=True,
        check=True,
    )
    proc = subprocess.run(
        ["docker", "exec", container, "pg_restore", "--list", container_path],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = f"pg_restore --list failed: {proc.stderr}"
        raise RuntimeError(msg)
    return proc.stdout
