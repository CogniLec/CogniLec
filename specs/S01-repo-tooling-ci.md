# S01 — Repository, Tooling & CI Skeleton
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Initialize the LIS monorepo with Python 3.12 + uv, complete CI pipeline, pre-commit hooks, and ADR register — all gates passing on a trivial PR.

**Component Boundaries:**
- **Allowed:** `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `docs/adrs/`, `src/`, `migrations/`, `notebooks/`, `docker/`, `config/`, `tests/`, `scripts/`, `.env.example`, `.gitignore`, `.sops.yaml`
- **Off-limits:** Application code in `src/` (handled in later stages), Docker compose files (S03), GPU Dockerfiles (S02)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12.x | Runtime |
| uv | 0.5.x | Package/venv manager |
| Ruff | 0.6.x | Lint/format |
| mypy | 1.11.x | Type checking (strict) |
| pre-commit | 3.8.x | Git hooks |
| gitleaks | 8.18.x | Secret detection |
| sqlfluff | 3.1.x | SQL linting |
| pytest | 8.3.x | Testing |
| GitHub Actions | — | CI/CD |

---

### 2. State Machine & Domain Schemas

**`pyproject.toml` Schema (key sections):**
```toml
[project]
name = "lis"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [...]  # pinned exact versions
[tool.ruff]
line-length = 100
target-version = "py312"
select = ["E","F","I","N","UP","W","C4","PTH","PIE","T20","TRY","SIM","RUF"]
[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
disallow_any_generics = true
```

**`.pre-commit-config.yaml` Schema:**
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks: [{id: ruff-check, args: [--fix]}, {id: ruff-format}]
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.2
    hooks: [{id: mypy, args: [--strict]}]
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks: [{id: gitleaks}]
  - repo: https://github.com/sqlfluff/sqlfluff
    rev: 3.1.0
    hooks: [{id: sqlfluff-lint}]
```

**ADR Template (`docs/adrs/template.md`):**
```markdown
# ADR-XXX: <Title>

## Status
<Proposed|Accepted|Superseded|Deprecated>

## Context
<Why this decision is needed>

## Decision
<What we decided>

## Consequences
<Trade-offs, follow-up work>

## Follow-up
<Links to related ADRs/stages>
```

**ADR Register (18 ADRs):**
| ID | Title | Source |
|----|-------|--------|
| 001 | Use Prefect for Pipeline Orchestration | Architecture v1.0 |
| 002 | Worker Pool Topology | Architecture v1.0 |
| 003 | Event-Driven Pipeline Triggers | Architecture v1.0 |
| 004 | Dual PostgreSQL Instances with FDW | Architecture v1.0 |
| 005 | Subject Partitioning via pg_partman | Architecture v1.0 |
| 006 | Custom TextTiling Segmentation | Architecture v1.0 |
| 007 | Six Independent LLM Agents | Architecture v1.0 |
| 008 | Copyright-Safe Visual Enrichment | Architecture v1.0 |
| 009 | Anonymous Diarisation Only | Architecture v1.0 |
| 010 | Subject-Scoped Topic Identity | Architecture v1.0 |
| 011 | GPU-Enabled Ensemble ASR | Architecture v1.0 |
| 012 | Fine-Tuning Flywheel | Architecture v1.0 |
| 013 | Row-Level Security for Data Isolation | Architecture v1.0 |
| 014 | Two-Phase Architecture | Architecture v1.0 |
| 015 | 4GB VRAM Constraint — Model Selection | **This project** |
| 016 | Hybrid LLM Ladder (Local → CPU → Hosted) | **This project** |
| 017 | 8-Bit Quantization for ASR/Embedding | **This project** |
| 018 | Local-First ASR and Embedding | **This project** |

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create directory structure | `tree -L 2` shows all dirs |
| 2 | Write `pyproject.toml` with all deps | `uv sync` succeeds |
| 3 | Write `.pre-commit-config.yaml` | `pre-commit run --all-files` passes |
| 4 | Write `.github/workflows/ci.yml` | Push to GitHub → CI green |
| 5 | Write `.gitignore`, `.env.example` | `git status` clean |
| 6 | Write `.sops.yaml` template | `sops --version` works |
| 7 | Create `docs/adrs/` with 18 ADR files | `ls docs/adrs/ | wc -l` = 18 |
| 8 | Install pre-commit hooks | `pre-commit install` succeeds |
| 9 | Test gitleaks with dummy secret | `echo "AWS_KEY=AKIA..." > test.txt && gitleaks detect` fails |
| 10 | Test mypy strict on skeleton | `mypy --strict src/` passes |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| `uv sync` fails on version conflict | Pin all deps exactly; no floating versions |
| pre-commit hook fails on CI but not locally | Ensure `.pre-commit-config.yaml` matches local |
| gitleaks false positive | Document exception in `.gitleaksignore` |
| mypy strict fails on empty `src/` | Add `src/__init__.py` with `py.typed` marker |

---

### 4. Code Style & Architecture Constraints

- **Line length:** 100 chars (Ruff)
- **Quotes:** Double (Ruff format)
- **Imports:** Sorted by Ruff (isort compatible)
- **Naming:** snake_case (Python), kebab-case (files), PascalCase (classes)
- **Type hints:** Required everywhere (mypy strict)
- **Max function length:** 40 lines
- **Max file length:** 300 lines
- **No `Any` type** without explicit `# type: ignore` + comment
- **Conventional Commits:** `type(scope): subject` — enforced by CI

---

### 5. API & Interface Contracts

**GitHub Actions Workflow (`.github/workflows/ci.yml`):**
```yaml
jobs:
  lint-and-typecheck: {runs-on: ubuntu-latest, steps: [uv sync, ruff check, ruff format --check, mypy --strict]}
  gitleaks: {runs-on: ubuntu-latest, steps: [gitleaks detect]}
  unit-tests: {runs-on: ubuntu-latest, services: [postgres, valkey, minio], steps: [pytest -m unit]}
  integration-tests: {runs-on: ubuntu-latest, services: [...], steps: [pytest -m integration]}
  docker-build: {runs-on: ubuntu-latest, steps: [docker build base-gpu]}
  cuda-matrix-check: {runs-on: ubuntu-latest, steps: [check all Dockerfiles match cuda-matrix.md]}
```

**CLI Commands:**
```bash
uv sync                    # Install all deps
uv run pytest -m unit      # Unit tests
uv run pytest -m integration  # Integration tests
uv run ruff check --fix .  # Lint + auto-fix
uv run ruff format .       # Format
uv run mypy --strict src/  # Type check
uv run sqlfluff lint migrations/  # SQL lint
pre-commit run --all-files # All hooks
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables (from `.env.example`):**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `POSTGRES_PASSWORD` | string | PG-MAIN password | `changeme` |
| `MINIO_ROOT_PASSWORD` | string | MinIO admin password | `changeme` |
| `SECRET_KEY` | string | JWT signing key (32+ chars) | `openssl rand -hex 32` |
| `TRAEFIK_EMAIL` | string | ACME email for TLS | `admin@lis.local` |

**Version Pins (enforced by CI):**
- Python 3.12.x
- uv 0.5.x
- All deps in `pyproject.toml` pinned to exact versions

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T01.1 | U | `uv sync` | Resolves on linux/mac/windows runners |
| T01.2 | U | `pre-commit run --all-files` | Passes on clean repo; fails on bad format |
| T01.3 | S | `gitleaks detect --source .` | Detects planted `AWS_SECRET=...` |
| T01.4 | U | `mypy --strict src/` | Exit code 0 |
| T01.5 | U | `sqlfluff lint migrations/` | Exit code 0 (empty dir ok) |
| T01.6 | U | `conventional-commit check` | Passes on `feat: test`, fails on `bad commit` |

**Verification Commands:**
```bash
# Full local verification
uv sync && \
uv run ruff check . && \
uv run ruff format --check . && \
uv run mypy --strict src/ && \
uv run pytest tests/ -m unit -v && \
gitleaks detect --source . --verbose
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| CI flakes (network) | Job fails intermittently | Re-run once via GitHub Actions UI |
| gitleaks false positive | Fails on legitimate code | Add to `.gitleaksignore` with comment |
| mypy false positive | Strict mode blocks valid code | Add `# type: ignore[code]` with explanation |
| Dependency conflict | `uv sync` fails | Check `pyproject.toml` for version overlap; all pins must be compatible |
| ADR missing | `ls docs/adrs/ | wc -l` < 18 | Create missing ADR from template |
