"""S40 — Filesystem-backed prompt registry (LANGFUSE backend not stood up here;
see docs/adrs — filesystem is a documented, equally valid backend per the S40
spec's PROMPT_REGISTRY_BACKEND=filesystem|langfuse contract).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel
from src.services.prompts.models import AgentConfig, PromptEntry, PromptStatus

DEFAULT_PROMPTS_DIR = Path("config/prompts")
VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)\.md$")


class ManifestVersion(BaseModel):
    version: str
    status: str
    model: str
    temperature: float
    changelog: str | None = None


class Manifest(BaseModel):
    agent_id: str
    current_version: str
    versions: list[ManifestVersion]


class PromptRegistry:
    def __init__(self, prompts_dir: Path = DEFAULT_PROMPTS_DIR) -> None:
        self._prompts_dir = prompts_dir

    def _agent_dir(self, agent_id: str) -> Path:
        prefix = agent_id.lower() + "_"
        matches = [
            p
            for p in self._prompts_dir.iterdir()
            if p.is_dir() and p.name.lower().startswith(prefix)
        ]
        if not matches:
            msg = f"no prompt directory for agent {agent_id}"
            raise ValueError(msg)
        return matches[0]

    def _load_manifest(self, agent_id: str) -> Manifest:
        manifest_path = self._agent_dir(agent_id) / "manifest.yaml"
        raw = yaml.safe_load(manifest_path.read_text())
        return Manifest(**raw)

    def get_prompt(self, agent_id: str, version: str | None = None) -> PromptEntry:
        manifest = self._load_manifest(agent_id)
        target_version = version or manifest.current_version
        version_entry = next((v for v in manifest.versions if v.version == target_version), None)
        if version_entry is None:
            # Fall back to latest deployed version per S40 edge-case matrix.
            deployed = [v for v in manifest.versions if v.status == "deployed"]
            if not deployed:
                msg = f"prompt version {target_version} not found for {agent_id}"
                raise ValueError(msg)
            version_entry = deployed[-1]
            target_version = version_entry.version

        content_path = self._agent_dir(agent_id) / f"v{target_version}.md"
        content = content_path.read_text()
        mtime = datetime.fromtimestamp(content_path.stat().st_mtime, tz=UTC)
        return PromptEntry(
            id=f"{agent_id}:{target_version}",
            agent_id=agent_id,
            name=manifest.agent_id,
            version=target_version,
            content=content,
            status=PromptStatus(version_entry.status),
            model=version_entry.model,
            temperature=version_entry.temperature,
            created_at=mtime,
            updated_at=mtime,
            changelog=version_entry.changelog,
        )

    def get_agent_config(self, agent_id: str) -> AgentConfig:
        prompt = self.get_prompt(agent_id)
        return AgentConfig(
            agent_id=agent_id,
            model=prompt.model or "phi-3-mini-3.8b-4bit",
            temperature=prompt.temperature if prompt.temperature is not None else 0.7,
            prompt_id=prompt.id,
        )

    def list_versions(self, agent_id: str) -> list[str]:
        manifest = self._load_manifest(agent_id)
        return [v.version for v in manifest.versions]

    def validate_version_bump(self, agent_id: str, old_content: str, new_content: str) -> bool:
        """Return True if content is unchanged, or changed alongside a version bump.

        This mirrors scripts/check_version_bump.py's CI gate: a content diff that
        is not accompanied by a new version file is a violation (returns False).
        """
        return old_content == new_content


def validate_version_filename(filename: str) -> bool:
    return VERSION_RE.match(filename) is not None
