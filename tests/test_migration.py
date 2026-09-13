"""T07.5 – Alembic upgrade/downgrade roundtrip test."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ALEMBIC_BIN = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "alembic"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_alembic(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run an alembic command and return the result."""
    return subprocess.run(
        [str(ALEMBIC_BIN), *command],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=60,
    )


@pytest.mark.integration
class TestMigrationRoundtrip:
    """T07.5 – Alembic upgrade head then downgrade base leaves clean DB."""

    async def test_upgrade_downgrade_roundtrip(self, db_session: AsyncSession) -> None:
        # Upgrade to head (conftest already did this, but verify it's at head)
        proc = _run_alembic(["current"])
        assert proc.returncode == 0, f"alembic current failed: {proc.stderr}"

        # Verify tables exist
        result = await db_session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
        tables = {row[0] for row in result.fetchall()}
        assert "users" in tables
        assert "subjects" in tables
        assert "sessions" in tables
        assert "agent_runs" in tables

        # Downgrade to base
        proc = _run_alembic(["downgrade", "base"])
        assert proc.returncode == 0, f"alembic downgrade base failed: {proc.stderr}"

        # Verify tables are gone
        result = await db_session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        remaining = {row[0] for row in result.fetchall()}
        core_tables = {"users", "subjects", "sessions", "agent_runs"}
        assert not core_tables.intersection(remaining), (
            f"Core tables still exist after downgrade: {core_tables.intersection(remaining)}"
        )

        # Upgrade back to head
        proc = _run_alembic(["upgrade", "head"])
        assert proc.returncode == 0, f"alembic upgrade head failed: {proc.stderr}"

        # Verify tables are back
        result = await db_session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
        tables = {row[0] for row in result.fetchall()}
        assert "users" in tables
        assert "subjects" in tables
        assert "sessions" in tables
        assert "agent_runs" in tables
