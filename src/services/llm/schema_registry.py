"""S38 — Central Pydantic/JSON-Schema registry for agent outputs A1-A6."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel
from src.services.llm.schemas.a1_concept_tutor import A1Output
from src.services.llm.schemas.a2_problem_coach import A2Output
from src.services.llm.schemas.a3_socratic_guide import A3Output
from src.services.llm.schemas.a4_study_planner import A4Output
from src.services.llm.schemas.a5_exam_sim import A5Output
from src.services.llm.schemas.a6_progress_analyst import A6Output

DEFAULT_SCHEMA_DIR = Path("config/schemas")


class AgentID(StrEnum):
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"
    A5 = "A5"
    A6 = "A6"


class SchemaEntry(BaseModel):
    agent_id: AgentID
    schema_name: str
    schema_dict: dict[str, object]
    version: str
    grammar_path: str | None = None
    last_updated: str


class ValidationFailure(BaseModel):
    agent_id: AgentID
    raw_output: str
    error_message: str
    tier: str
    attempt: int
    timestamp: str


_MODEL_BY_AGENT: dict[AgentID, type[BaseModel]] = {
    AgentID.A1: A1Output,
    AgentID.A2: A2Output,
    AgentID.A3: A3Output,
    AgentID.A4: A4Output,
    AgentID.A5: A5Output,
    AgentID.A6: A6Output,
}


class SchemaRegistry:
    """Loads and validates all agent output schemas at startup (fail-fast).

    CI enforces this at import time: `SchemaRegistry()` raises if any of
    A1-A6 is missing a `config/schemas/<agent>.json` file.
    """

    REQUIRED_AGENTS: ClassVar[list[AgentID]] = list(AgentID)

    def __init__(self, schema_dir: Path = DEFAULT_SCHEMA_DIR) -> None:
        self._schema_dir = schema_dir
        self._entries: dict[AgentID, SchemaEntry] = {}
        self._load_all()

    def _load_all(self) -> None:
        missing: list[str] = []
        for agent in self.REQUIRED_AGENTS:
            path = self._schema_dir / f"{agent.value.lower()}.json"
            if not path.exists():
                missing.append(agent.value)
                continue
            raw = json.loads(path.read_text())
            self._entries[agent] = SchemaEntry(
                agent_id=agent,
                schema_name=raw["schema_name"],
                schema_dict=raw["schema"],
                version=raw["version"],
                grammar_path=raw.get("grammar_path"),
                last_updated=raw.get("last_updated", datetime.now(UTC).isoformat()),
            )
        if missing:
            msg = f"missing registered schema for agents: {missing}"
            raise ValueError(msg)

    def get_schema(self, agent_id: AgentID) -> SchemaEntry:
        if agent_id not in self._entries:
            msg = f"no schema registered for agent {agent_id}"
            raise ValueError(msg)
        return self._entries[agent_id]

    def validate_output(self, agent_id: AgentID, output: str) -> dict[str, object]:
        model_cls = _MODEL_BY_AGENT[agent_id]
        parsed = json.loads(output)
        validated = model_cls.model_validate(parsed)
        return validated.model_dump()

    def get_grammar(self, agent_id: AgentID) -> str | None:
        return self.get_schema(agent_id).grammar_path

    def list_schemas(self) -> list[SchemaEntry]:
        return list(self._entries.values())


def get_output_model(agent_id: AgentID) -> type[BaseModel]:
    """Return the Pydantic model backing an agent's schema, for grammar compilation."""
    return _MODEL_BY_AGENT[agent_id]
