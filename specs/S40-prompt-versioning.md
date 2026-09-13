# S40 — Prompt Versioning & Regression Testing
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Version all prompts by reference (not inlined), run promptfoo regression suites in CI, and block merges on prompt-induced quality degradation.

**Component Boundaries:**
- **Allowed:** `config/prompts/`, `src/services/prompts/`, `tests/test_prompt_versioning.py`, `.promptfoo/`, CI workflow files
- **Off-limits:** Observability (S39), schema registry (S38), agent implementations (S56–S57)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| promptfoo | 0.x | Prompt regression testing |
| LangFuse | 2.x | Prompt versioning and registry |
| Pydantic | 2.x | Schema definitions |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Prompt Lifecycle:**
```
draft → versioned → tested → deployed → archived
  ↓         ↓          ↓         ↓
  CI runs  CI runs   CI runs   No CI
  suite    suite     suite
```

**Pydantic Models:**
```python
# src/services/prompts/models.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class PromptStatus(str, Enum):
    DRAFT = "draft"
    VERSIONED = "versioned"
    TESTED = "tested"
    DEPLOYED = "deployed"
    ARCHIVED = "archived"


class PromptEntry(BaseModel):
    id: str
    agent_id: str
    name: str
    version: str  # semver: 1.0.0
    content: str
    status: PromptStatus
    model: str | None = None  # per-agent model override
    temperature: float | None = None  # per-agent temperature override
    created_at: datetime
    updated_at: datetime
    changelog: str | None = None


class AgentConfig(BaseModel):
    agent_id: str
    model: str = "phi-3-mini-3.8b-4bit"
    temperature: float = 0.7
    prompt_id: str  # references PromptEntry.id
    max_tokens: int = 2048


class RegressionResult(BaseModel):
    agent_id: str
    prompt_version: str
    total_cases: int
    passed: int
    failed: int
    pass_rate: float
    failed_cases: list[dict] | None = None
```

**Prompt Registry (LangFuse or git files):**
```
config/prompts/
├── a1_concept_tutor/
│   ├── v1.0.0.md
│   ├── v1.1.0.md
│   └── manifest.yaml
├── a3_socratic_guide/
│   ├── v1.0.0.md
│   └── manifest.yaml
└── ...
```

**manifest.yaml:**
```yaml
agent_id: A1
current_version: 1.1.0
versions:
  - version: 1.0.0
    status: archived
    model: phi-3-mini-3.8b-4bit
    temperature: 0.7
  - version: 1.1.0
    status: deployed
    model: phi-3-mini-3.8b-4bit
    temperature: 0.7
    changelog: "Improved explanation clarity"
```

**State Transition Rules:**
- Draft → Versioned: when version is bumped and file committed
- Versioned → Tested: when promptfoo suite runs and passes
- Tested → Deployed: when CI gate passes and merged to main
- Deployed → Archived: when superseded by new version
- Any version change without bump → CI fails (T40.1)

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create `config/prompts/` directory structure with manifest files | All agents have prompt directories |
| 2 | Define Pydantic models for `PromptEntry` and `AgentConfig` | Models validate correctly |
| 3 | Implement `PromptRegistry` that loads prompts by version | Registry loads all agent prompts |
| 4 | Create promptfoo test suites per agent with golden cases | promptfoo runs and reports results |
| 5 | Wire CI workflow to run promptfoo on prompt file changes | CI blocks on regression |
| 6 | Implement version-bump detection in CI | CI fails if prompt changed without version bump |
| 7 | Implement per-agent model/temperature config | Config applied without code change |
| 8 | Wire `agent_runs.prompt_version` recording | Every run has prompt version |

**Atomic Sub-tasks:**
1. Prompt directory structure and manifest files
2. PromptRegistry with version-aware loading
3. promptfoo golden test suites per agent
4. CI workflow for prompt regression
5. Version-bump detection gate
6. Per-agent model/temperature configuration
7. `agent_runs.prompt_version` integration

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Prompt changed without version bump | CI fails, block merge |
| promptfoo suite fails | CI fails, block merge |
| Prompt file missing for agent | CI fails, block merge |
| Prompt version not found | Fall back to latest deployed version |
| Per-agent config has invalid model | Fail fast with clear error |
| Golden cases outdated | Update golden cases, bump prompt version |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Registry pattern: `PromptRegistry` centralizes prompt management
- Versioning pattern: semver with manifest tracking
- Gate pattern: CI workflow as quality gate

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase
- Files: snake_case for Python, kebab-case for prompt files
- Prompt files: `v{major}.{minor}.{patch}.md`

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- One prompt file per version per agent

**Type Safety:**
- All schemas are Pydantic v2 models
- `from __future__ import annotations` in all files
- Version strings validated as semver

---

### 5. API & Interface Contracts

**PromptRegistry Interface:**
```python
# src/services/prompts/registry.py
class PromptRegistry:
    def get_prompt(self, agent_id: str, version: str | None = None) -> PromptEntry:
        """Get prompt for agent. If version is None, return deployed version."""
        ...

    def get_agent_config(self, agent_id: str) -> AgentConfig:
        """Get per-agent model/temperature config."""
        ...

    def list_versions(self, agent_id: str) -> list[str]:
        """List all versions for an agent."""
        ...

    def validate_version_bump(self, agent_id: str, old_content: str, new_content: str) -> bool:
        """Check if content changed without version bump."""
        ...
```

**Promptfoo Config (`.promptfoo/config.yaml`):**
```yaml
description: LIS Agent Prompt Regression Suite

prompts:
  - file://config/prompts/a1_concept_tutor/v1.1.0.md

providers:
  - id: openai:gpt-4o-mini
    label: Hosted Tier
  - id: vllm:phi-3-mini-3.8b-4bit
    label: Local Tier

tests:
  - file://tests/promptfoo/a1_golden.jsonl

defaultTest:
  assert:
    - type: is-json
    - type: javascript
      value: "output.key_concepts.length >= 1"
    - type: llm-rubric
      value: "Response is a clear, accurate explanation suitable for a student"
```

**Golden Test Cases (`.promptfoo/tests/a1_golden.jsonl`):**
```json
{"vars": {"topic": "photosynthesis", "level": "beginner"}, "assert": [{"type": "contains", "value": "photosynthesis"}, {"type": "llm-rubric", "value": "Explanation is accurate and student-friendly"}]}
{"vars": {"topic": "quantum entanglement", "level": "advanced"}, "assert": [{"type": "contains", "value": "quantum"}, {"type": "javascript", "value": "output.difficulty === 'hard'"}]}
{"vars": {"topic": "Newton's laws", "level": "intermediate"}, "assert": [{"type": "contains", "value": "Newton"}, {"type": "javascript", "value": "output.key_concepts.length >= 2"}]}
```

**CI Workflow (`.github/workflows/prompt-regression.yaml`):**
```yaml
name: Prompt Regression Suite
on:
  push:
    paths:
      - 'config/prompts/**'
      - '.promptfoo/**'
  pull_request:
    paths:
      - 'config/prompts/**'
      - '.promptfoo/**'

jobs:
  prompt-regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: promptfoo/promptfoo-action@v1
        with:
          config: .promptfoo/config.yaml
          prompt-files: config/prompts/**/*.md
      - name: Version Bump Check
        run: |
          python scripts/check_version_bump.py
```

**Version Bump Check Script (`scripts/check_version_bump.py`):**
```python
#!/usr/bin/env python3
"""Check that prompt file changes include a version bump."""

import sys
import subprocess
import re
import yaml


def main():
    changed_files = (
        subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD~1", "config/prompts/"], text=True
        )
        .strip()
        .split("\n")
    )

    for f in changed_files:
        if not f.endswith(".md"):
            continue
        # Extract version from filename
        match = re.search(r"v(\d+\.\d+\.\d+)\.md", f)
        if not match:
            print(f"ERROR: Prompt file {f} does not follow version naming convention")
            sys.exit(1)

        # Check manifest
        manifest_path = f.rsplit("/", 1)[0] + "/manifest.yaml"
        try:
            with open(manifest_path) as fh:
                manifest = yaml.safe_load(fh)
            if manifest.get("current_version") != match.group(1):
                print(
                    f"WARNING: {f} version {match.group(1)} differs from manifest current_version {manifest.get('current_version')}"
                )
        except FileNotFoundError:
            print(f"WARNING: No manifest found at {manifest_path}")

    print("Version bump check passed")


if __name__ == "__main__":
    main()
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `PROMPT_REGISTRY_BACKEND` | string | `langfuse` or `filesystem` | `filesystem` |
| `LANGFUSE_HOST` | string | LangFuse URL (if using LangFuse backend) | — |
| `PROMPTFOO_API_KEY` | string | promptfoo cloud API key (optional) | — |
| `DEFAULT_MODEL` | string | Default model for agents | `phi-3-mini-3.8b-4bit` |
| `DEFAULT_TEMPERATURE` | float | Default temperature | `0.7` |

**Third-Party Integration Contracts:**
- LangFuse: prompt storage and versioning API (if using LangFuse backend)
- promptfoo: CLI-based regression testing

**Version Pins:**
- promptfoo pinned in CI workflow
- LangFuse Python SDK pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T40.1 | U | `pytest tests/test_prompt_versioning.py::test_version_bump_required -v` | Changing prompt without version bump fails CI |
| T40.2 | I | `pytest tests/test_prompt_versioning.py::test_promptfoo_suite_runs -v` | promptfoo suite runs and reports per-case results |
| T40.3 | I | `pytest tests/test_prompt_versioning.py::test_degraded_prompt_caught -v` | Deliberately degraded prompt is caught by regression suite |
| T40.4 | I | `pytest tests/test_prompt_versioning.py::test_model_swap_by_config -v` | Agent model swapped by config alone, no code change |
| T40.5 | I | `pytest tests/test_prompt_versioning.py::test_prompt_version_recorded -v` | Prompt version recorded on every `agent_runs` row |

**Test Case Details (Given/When/Then):**

**T40.1 — Changing prompt without version bump fails CI**
- **Given:** a committed prompt at version 1.0.0
- **When:** the prompt content is modified without updating the version in the filename or manifest
- **Then:** CI workflow fails with "Version bump required" error

**T40.2 — promptfoo suite runs in CI**
- **Given:** a promptfoo config with golden test cases for A1
- **When:** the CI workflow triggers on a prompt change
- **Then:** promptfoo runs all golden cases, reports pass/fail per case, CI exits with appropriate code

**T40.3 — Deliberately degraded prompt caught**
- **Given:** a prompt modified to produce garbage output (e.g., "Always respond with 'I don't know'")
- **When:** the promptfoo regression suite runs
- **Then:** golden cases fail, CI blocks merge

**T40.4 — Agent model swapped by config**
- **Given:** agent A1 configured with `model: gpt-4o-mini` in `AgentConfig`
- **When:** the agent processes a request
- **Then:** the request is routed to `gpt-4o-mini` without any code change; `agent_runs.model` shows `gpt-4o-mini`

**T40.5 — Prompt version recorded on every run**
- **Given:** a session with agent A1 using prompt version 1.1.0
- **When:** the session completes
- **Then:** `agent_runs` row has `prompt_version = '1.1.0'`

**Verification Commands:**
```bash
uv run pytest tests/test_prompt_versioning.py -v -k "S40 or prompt" && \
promptfoo eval -c .promptfoo/config.yaml && \
uv run mypy --strict src/services/prompts/ && \
uv run ruff check src/services/prompts/
```

**Exit Criteria:**
- [ ] T40.1 passes — version bump required for prompt changes
- [ ] T40.2 passes — promptfoo suite runs and reports results
- [ ] T40.3 passes — degraded prompt caught by regression suite
- [ ] T40.4 passes — model swapped by config, no code change
- [ ] T40.5 passes — prompt version recorded on every `agent_runs` row

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Golden cases must be updated when prompt behavior intentionally changes — stale golden cases block legitimate improvements
- promptfoo CI action may timeout on large suites — split suites per agent if needed
- Version naming convention (`v{major}.{minor}.{patch}.md`) must be enforced — invalid names bypass version check
- Prompt content in LangFuse must match filesystem if using dual backend

**Fallback Instructions:**
- If promptfoo CI action fails: check for API key issues, provider availability, or suite timeout
- If version bump check has false positives: review git diff for false changes (whitespace-only)
- If golden cases are outdated: update cases, bump prompt version, re-run suite

**Rollback Procedure:**
- Revert prompt file to previous version
- Re-run promptfoo suite against reverted version
- No database changes — prompt versioning is file-based
- `agent_runs.prompt_version` is append-only, historical data preserved

---

### 9. Observability (if applicable)

**Metrics Added:**
- `prompt_regression_suite_total`: counter of promptfoo suite runs (labels: agent_id, pass/fail)
- `prompt_regression_pass_rate`: gauge of pass rate per agent
- `prompt_version_changes_total`: counter of prompt version bumps

**Tracing/Logging:**
- Log: INFO on promptfoo suite completion with pass rate
- Log: WARNING on regression detection (degraded prompt)
- Log: ERROR on version bump check failure

**Alerts:**
- Regression suite fails for any agent: block merge, notify team
- Prompt version drift between manifest and filesystem: warning

---

### 10. Exit Checklist

- [ ] All tests pass (T40.1, T40.2, T40.3, T40.4, T40.5)
- [ ] Prompt registry loads all agent prompts by version
- [ ] promptfoo golden suites exist for all agents A1–A6
- [ ] CI workflow blocks merge on regression
- [ ] Version bump detection enforces semver
- [ ] Per-agent model/temperature configurable without code change
- [ ] `agent_runs.prompt_version` populated for every invocation
