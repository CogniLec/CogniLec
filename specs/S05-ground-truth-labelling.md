# S05 — Ground Truth & Labelling Infrastructure
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy Label Studio, create three labelled datasets (word-level transcripts, topic boundaries/labels, relevance labels), and build a validated evaluation harness.

**Component Boundaries:**
- **Allowed:** Label Studio (Docker), `src/eval/harness.py`, DVC-tracked labels, rubric docs
- **Off-limits:** ASR models (S06), segmentation (S28), clustering (S30)

**Tech Stack:**
| Tool | Version | Purpose |
|------|---------|---------|
| Label Studio | 1.12.0 | Data labelling UI |
| jiwer | 3.0.4 | WER computation |
| segeval | 0.1.2 | P_k, WindowDiff |
| scikit-learn | 1.5.1 | Purity, V-measure, Cohen's kappa |
| DVC | 3.52.x | Label versioning |
| pandas | 2.2.2 | Data manipulation |

---

### 2. State Machine & Domain Schemas

**Label Studio Project 1: Word-Level Transcription**
```json
{
  "title": "LIS Word-Level Transcription",
  "label_config": "<View><Audio name=\"audio\" value=\"$audio\"/><TextArea name=\"transcript\" toName=\"audio\" editable=\"true\" rows=\"4\"/></View>",
  "data": {"audio": "/data/lis-eval/phase0/v1/sess_001/audio.opus"}
}
```
- 5 hours total from S04 corpus
- Word-level timestamps via Label Studio audio regions

**Label Studio Project 2: Topic Boundaries & Labels**
```json
{
  "title": "LIS Topic Segmentation",
  "label_config": "<View><Audio name=\"audio\" value=\"$audio\"/><Labels name=\"topics\" toName=\"audio\"><Label value=\"Topic A\"/><Label value=\"Topic B\"/></Labels></View>",
  "data": {"audio": "/data/lis-eval/phase0/v1/sess_001/audio.opus"}
}
```
- 30 lecture-equivalents (can reuse S04 sessions)
- Annotators mark segment boundaries + assign topic labels

**Label Studio Project 3: Relevance Labelling**
```json
{
  "title": "LIS Relevance Classification",
  "label_config": "<View><Text name=\"utterance\" value=\"$text\"/><Choices name=\"relevance\" toName=\"utterance\"><Choice value=\"on_topic\"/><Choice value=\"off_topic\"/></Choices></View>",
  "data": {"text": "Professor: Today we'll cover photosynthesis..."}
}
```
- 2,000 utterances sampled across conditions
- Rubric in `docs/relevance-rubric.md`:
  - **on_topic**: Core content, relevant student questions, clarifications
  - **off_topic**: Admin announcements, off-topic chatter, lecturer tangents, technical issues

**Eval Harness Schema (`src/eval/harness.py`):**
```python
from pydantic import BaseModel
from typing import Literal

class EvalInput(BaseModel):
    dataset: Literal["wer", "segmentation", "relevance", "clustering"]
    reference: list  # Ground truth
    predictions: list  # Model output

class EvalOutput(BaseModel):
    wer: float | None = None
    pk: float | None = None
    window_diff: float | None = None
    purity: float | None = None
    v_measure: float | None = None
    kappa: float | None = None

def run_eval(dataset: str, reference: list, predictions: list) -> EvalOutput:
    """Single entry point for all evaluations."""
```

**DVC Label Structure:**
```
lis-eval/labels/v1/
├── transcripts/      # Project 1 exports
├── boundaries/       # Project 2 exports
├── relevance/        # Project 3 exports
├── rubric.md         # Relevance rubric
└── .dvc/
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Command |
|------|--------|---------|
| 1 | Label Studio already running (S03) | `docker compose ps label-studio` |
| 2 | Create Project 1 (Transcription) | UI: Import S04 audio tasks; configure label config |
| 3 | Transcribe 5 hours | Annotators: play audio, type transcript, mark word regions |
| 4 | Export Project 1 | UI: Export -> JSON -> save to `lis-eval/labels/v1/transcripts/` |
| 5 | Create Project 2 (Boundaries) | UI: Import same audio; label config for segments |
| 6 | Mark 30 lectures | Annotators: mark boundaries, assign topic labels |
| 7 | Export Project 2 | Save to `lis-eval/labels/v1/boundaries/` |
| 8 | Create Project 3 (Relevance) | UI: Import 2000 utterances from Project 1 |
| 9 | Label relevance | Annotators: apply rubric, choose on/off-topic |
| 10 | Export Project 3 | Save to `lis-eval/labels/v1/relevance/` |
| 11 | Write rubric | `docs/relevance-rubric.md` with examples |
| 12 | DVC track labels | `dvc add lis-eval/labels/v1/ && dvc push` |
| 13 | Build eval harness | Write `src/eval/harness.py` with `run_eval()` |
| 14 | Unit test harness | `pytest tests/test_eval_harness.py` |
| 15 | Validate kappa | `python scripts/check_kappa.py` |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Label Studio import fails | Check audio URLs accessible (MinIO presigned) |
| Annotator disagreement high | Review rubric; add examples; re-label overlap set |
| Harness metric mismatch | Compare against known fixtures; debug jiwer/segeval params |
| DVC push fails | Check MinIO creds; bucket `lis-eval` exists |

---

### 4. Code Style & Architecture Constraints

- **Single entry point:** `run_eval(dataset, reference, predictions)` — no CLI, pure function
- **Deterministic metrics:** Fixed random seeds for any stochastic components
- **Label versioning:** DVC commits for every label export; git tags for major versions
- **Rubric as code:** `docs/relevance-rubric.md` is source of truth; annotators trained on it
- **No PII in labels:** Only utterance text + labels; no speaker info

---

### 5. API & Interface Contracts

**Label Studio API (for automation):**
```bash
# Import tasks
curl -X POST http://label-studio:8080/api/projects/1/import \
  -H "Authorization: Token $LABEL_STUDIO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"audio": "http://minio:9000/lis-eval/phase0/v1/sess_001/audio.opus"}]'

# Export annotations
curl -X GET "http://label-studio:8080/api/projects/1/export?exportType=JSON" \
  -H "Authorization: Token $LABEL_STUDIO_TOKEN" > export.json
```

**Eval Harness Python API:**
```python
from src.eval.harness import run_eval, EvalInput, EvalOutput

# WER
result = run_eval("wer", reference_tokens, hypothesis_tokens)
print(result.wer)

# Segmentation (P_k, WindowDiff)
result = run_eval("segmentation", ref_boundaries, pred_boundaries)
print(result.pk, result.window_diff)

# Clustering (purity, V-measure)
result = run_eval("clustering", ref_labels, pred_labels)
print(result.purity, result.v_measure)

# Relevance (kappa)
result = run_eval("relevance", ref_labels, pred_labels)
print(result.kappa)
```

---

### 6. Dependency & Environment Configuration

**Label Studio Environment (docker-compose):**
```yaml
environment:
  LABEL_STUDIO_HOST: 0.0.0.0
  LABEL_STUDIO_PORT: 8080
  LABEL_STUDIO_DATABASE: sqlite:///label-studio/data/label-studio.db
  LABEL_STUDIO_USER_FILE: /run/secrets/label_studio_user
  LABEL_STUDIO_PASSWORD_FILE: /run/secrets/label_studio_password
```

**Required `.env`:**
```bash
LABEL_STUDIO_URL=http://label-studio:8080
LABEL_STUDIO_TOKEN=<from UI>
MLFLOW_TRACKING_URI=http://mlflow:5000
```

**DVC Remote (MinIO):**
```bash
dvc remote add -d labels s3://lis-eval/labels
dvc remote modify labels endpointurl http://minio:9000
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T05.1 | U | `pytest tests/test_eval_harness.py::test_wer_known_fixture` | WER matches known value |
| T05.2 | U | `pytest tests/test_eval_harness.py::test_pk_sanity` | Identical segs -> 0.0; inverted -> >0.5 |
| T05.3 | M | `python scripts/check_kappa.py` | kappa >= 0.75 (or self-consistency if solo) |
| T05.4 | U | `dvc status lis-eval/labels/v1/` | No changes (reproducible) |

**Verification Script (`scripts/check_kappa.py`):**
```python
#!/usr/bin/env python3
import json
from sklearn.metrics import cohen_kappa_score

# Load overlap annotations (200 utterances labelled by 2 annotators)
with open("lis-eval/labels/v1/relevance/overlap.json") as f:
    data = json.load(f)

ann1 = [d["annotator1"] for d in data]
ann2 = [d["annotator2"] for d in data]

kappa = cohen_kappa_score(ann1, ann2)
print(f"Cohen's kappa: {kappa:.3f}")

if kappa >= 0.75:
    print("PASS: kappa >= 0.75")
    exit(0)
else:
    print("FAIL: kappa < 0.75")
    exit(1)
```

**Verification Script (`scripts/verify_s05.sh`):**
```bash
#!/bin/bash
set -euo pipefail

echo "=== Verifying S05 Labelling ==="

# 1. Label Studio accessible
curl -kf https://label.lis.local >/dev/null && echo "Label Studio OK"

# 2. DVC labels reproducible
dvc pull lis-eval/labels/v1/
echo "DVC labels pulled"

# 3. Run eval harness unit tests
uv run pytest tests/test_eval_harness.py -v

# 4. Check kappa
python scripts/check_kappa.py

# 5. Verify rubric exists
[ -f docs/relevance-rubric.md ] && echo "Rubric exists"

echo "=== S05 VERIFIED ==="
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| Low inter-annotator kappa | `check_kappa.py` < 0.75 | Refine rubric; add ambiguous examples; re-train annotators |
| Label Studio 500 on export | UI error | Check SQLite disk space; restart container |
| Harness gives wrong WER | Unit test fails | Debug jiwer normalization; match `whisper-normalizer` |
| DVC label conflicts | `dvc status` shows changes | `dvc checkout` to restore; investigate concurrent edits |
| Relevance rubric ambiguous | Annotators ask many questions | Add more examples to `docs/relevance-rubric.md` |
| 30 lectures not available | Only 8-10 recorded | Reuse sessions with different topic splits; document |
