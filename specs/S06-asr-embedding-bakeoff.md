# S06 — ASR & Embedding Bake-Off (HARD GATE)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Run comprehensive ASR and embedding model bake-off on the GPU host (4GB VRAM) using fully local, open-source models with 8-bit quantization where needed. Lock production model decisions based on measurable gates.

**Component Boundaries:**
- **Allowed:** GPU host, S04 corpus, S05 ground truth, MLflow, `config/models.yaml`, bake-off scripts
- **Off-limits:** Hosted ASR APIs (per ADR-018), hosted embedding APIs, model fine-tuning (S65+)

**Tech Stack & Models (all local, open weights):**
| Category | Models | Inference Engine | Quantization |
|----------|--------|------------------|--------------|
| ASR | Whisper large-v3, large-v3-turbo, Canary-Qwen 2.5B, Parakeet TDT 1.1B | faster-whisper (CTranslate2) | int8_float16 (Whisper), 8-bit bitsandbytes (Canary), FP16 (Parakeet, turbo) |
| Embedding | Qwen3-Embedding-0.6B only | sentence-transformers / TEI | FP16 (fits 1.5GB) |
| Clustering | BERTopic (UMAP + HDBSCAN) | CPU | — |
| Tracking | MLflow 2.16.2 | Local (file:// or PG) | — |

---

### 2. State Machine & Domain Schemas

**MLflow Experiment Structure:**
```
Experiment: "S06_ASR_Bakeoff"
  Runs: one per (model, condition)
  Params: model_name, condition, quantization, compute_type
  Metrics: wer, cer, rtf, vram_peak_mb
  Artifacts: hypothesis.txt, reference.txt, alignment.json

Experiment: "S06_Embedding_Bakeoff"
  Runs: one per (embedding_model, dim, clustering_config)
  Params: model_name, dim, umap_n_neighbors, hdbscan_min_cluster_size
  Metrics: purity, v_measure, silhouette
  Artifacts: cluster_labels.json, topic_keywords.json
```

**ASR Results Table Schema (`docs/bakeoff-asr-results.csv`):**
```csv
model,condition,wer,cer,rtf,vram_peak_mb,quantization,compute_type
whisper-large-v3,front_quiet,0.12,0.05,0.3,3200,int8_float16,int8_float16
whisper-large-v3-turbo,front_quiet,0.14,0.06,0.15,2400,fp16,fp16
canary-qwen-2.5b,front_quiet,0.18,0.08,0.4,2800,8bit,float16
parakeet-tdt-1.1b,front_quiet,0.16,0.07,0.1,2200,fp16,fp16
...
```

**Embedding Results Table (`docs/bakeoff-embedding-results.csv`):**
```csv
model,dim,purity,v_measure,silhouette,umap_n_neighbors,hdbscan_min_cluster_size
qwen3-0.6b,1024,0.65,0.58,0.12,15,5
```

**Pairwise Disagreement Analysis (`docs/bakeoff-disagreement.csv`):**
```csv
model_a,model_b,disagreement_rate,wer_correlation
whisper-large-v3,whisper-large-v3-turbo,0.08,-0.72
whisper-large-v3,canary-qwen-2.5b,0.12,-0.68
...
```

**Locked Config (`config/models.yaml`):**
```yaml
asr_model: "whisper-large-v3-turbo"  # or winner
asr_model_revision: "main"
asr_compute_type: "int8_float16"  # or fp16 for turbo
asr_device: "cuda"
asr_beam_size: 5
asr_batch_size: 16

embedding_model: "Qwen/Qwen3-Embedding-0.6B"
embedding_dim: 1024
embedding_revision: "main"
embedding_device: "cuda"
embedding_batch_size: 32
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Script/Command |
|------|--------|----------------|
| 1 | Prepare environment | `scripts/s06_prepare.sh` (pulls S04/S05 via DVC) |
| 2 | Start MLflow | `docker compose up -d mlflow` |
| 3 | Run ASR bake-off | `python scripts/s06_asr_bakeoff.py` |
| 4 | Run embedding bake-off | `python scripts/s06_embedding_bakeoff.py` |
| 5 | Run disagreement analysis | `python scripts/s06_disagreement.py` |
| 6 | Generate reports | `python scripts/s06_report.py` |
| 7 | Check gates | `python scripts/s06_check_gates.py` |
| 8 | Freeze `config/models.yaml` | Write winning models |
| 9 | Commit results | `git add docs/bakeoff-*.md config/models.yaml` |

**ASR Bake-off Script (`scripts/s06_asr_bakeoff.py`):**
```python
#!/usr/bin/env python3
import mlflow
import torch
from faster_whisper import WhisperModel
from nemo.collections.asr.models import EncDecRNNTBPEModel  # Parakeet
import jiwer
import pandas as pd

MODELS = [
    ("whisper-large-v3", "large-v3", "int8_float16"),
    ("whisper-large-v3-turbo", "large-v3-turbo", "fp16"),
    ("canary-qwen-2.5b", "nvidia/canary-2.5b", "8bit"),
    ("parakeet-tdt-1.1b", "nvidia/parakeet-tdt-1.1b", "fp16"),
]

CONDITIONS = [
    "front_quiet",
    "back_quiet",
    "front_busy",
    "back_busy",
    "lecturer_moving",
    "heavy_discussion",
]


def load_model(name, model_id, quant):
    if "whisper" in name:
        return WhisperModel(model_id, device="cuda", compute_type=quant)
    elif "parakeet" in name:
        return EncDecRNNTBPEModel.from_pretrained(model_id).cuda().eval()
    # Canary similar...


def transcribe(model, audio_path):
    segments, info = model.transcribe(audio_path, beam_size=5, word_timestamps=True)
    return " ".join([s.text for s in segments])


def main():
    mlflow.set_experiment("S06_ASR_Bakeoff")

    for model_name, model_id, quant in MODELS:
        print(f"Loading {model_name} ({quant})...")
        model = load_model(model_name, model_id, quant)

        for condition in CONDITIONS:
            audio_files = get_audio_for_condition(condition)  # from S04 manifest

            for audio_file in audio_files:
                with mlflow.start_run(run_name=f"{model_name}_{condition}_{audio_file.stem}"):
                    mlflow.log_params(
                        {"model": model_name, "condition": condition, "quantization": quant}
                    )

                    # Transcribe
                    hypothesis = transcribe(model, audio_file)

                    # Load reference (S05 ground truth)
                    reference = load_reference(audio_file)

                    # Normalize
                    hyp_norm = jiwer.transforms.whisper_normalizer(hypothesis)
                    ref_norm = jiwer.transforms.whisper_normalizer(reference)

                    # Metrics
                    wer = jiwer.wer(ref_norm, hyp_norm)
                    cer = jiwer.cer(ref_norm, hyp_norm)
                    rtf = compute_rtf(audio_file)
                    vram = torch.cuda.max_memory_allocated() / 1e6

                    mlflow.log_metrics({"wer": wer, "cer": cer, "rtf": rtf, "vram_peak_mb": vram})
                    mlflow.log_artifact(hypothesis, "hypothesis.txt")

                    # Clear cache for next model
                    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
```

**Embedding Bake-off Script (`scripts/s06_embedding_bakeoff.py`):**
```python
#!/usr/bin/env python3
from sentence_transformers import SentenceTransformer
from bertopic import BERTopic
from sklearn.metrics import purity_score, v_measure_score
import mlflow

MODEL = "Qwen/Qwen3-Embedding-0.6B"
DIM = 1024


def main():
    mlflow.set_experiment("S06_Embedding_Bakeoff")

    # Load S05 hand-transcribed texts with topic labels
    texts, topic_labels = load_s05_labels()

    with mlflow.start_run(run_name=f"qwen3-0.6b_{DIM}d"):
        mlflow.log_params({"model": MODEL, "dim": DIM})

        # Embed
        model = SentenceTransformer(MODEL, device="cuda")
        embeddings = model.encode(texts, batch_size=32, show_progress_bar=True)

        # Cluster with BERTopic
        topic_model = BERTopic(
            embedding_model=model,
            umap_model=UMAP(n_neighbors=15, n_components=5, metric="cosine"),
            hdbscan_model=HDBSCAN(
                min_cluster_size=5, metric="euclidean", cluster_selection_method="eom"
            ),
        )
        topics, probs = topic_model.fit_transform(texts, embeddings)

        # Metrics
        purity = purity_score(topic_labels, topics)
        v_measure = v_measure_score(topic_labels, topics)

        mlflow.log_metrics({"purity": purity, "v_measure": v_measure})
        mlflow.log_artifact(topic_model.get_topic_info(), "topic_info.csv")

        print(f"Purity: {purity:.3f}, V-measure: {v_measure:.3f}")


if __name__ == "__main__":
    main()
```

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| OOM on model load | Sequential loading; `torch.cuda.empty_cache()` between models |
| Canary/Parakeet load fails | Check transformers version; fallback to HF hub |
| MLflow connection fails | Use `file:///mlflow` local tracking |
| WER > 35% on any condition | Flag as capture issue; escalate per gate |
| Purity < 0.60 | Try different UMAP/HDBSCAN params; document |

---

### 4. Code Style & Architecture Constraints

- **Sequential model loading:** Only one model in VRAM at a time (4GB constraint)
- **8-bit quantization mandatory** for models >2.5GB FP16 (Whisper large-v3, Canary)
- **No hosted APIs** — all inference local (ADR-018)
- **MLflow tracking:** Every run logged; artifacts stored in MinIO `lis-eval/mlflow/`
- **Whisper normalizer:** Applied to both reference and hypothesis for fair WER
- **Fixed random seeds:** For BERTopic reproducibility

---

### 5. API & Interface Contracts

**MLflow Tracking URI:** `http://mlflow:5000` (via docker-compose)

**CLI Commands:**
```bash
# Run full bake-off
python scripts/s06_run_all.py

# Run just ASR
python scripts/s06_asr_bakeoff.py

# Run just embedding
python scripts/s06_embedding_bakeoff.py

# Check gates
python scripts/s06_check_gates.py
```

**Gate Check Script (`scripts/s06_check_gates.py`):**
```python
#!/usr/bin/env python3
import mlflow
import pandas as pd

mlflow.set_tracking_uri("http://mlflow:5000")

# Load ASR results
asr_runs = mlflow.search_runs(experiment_names=["S06_ASR_Bakeoff"])
df_asr = pd.DataFrame(asr_runs)

# Gate 1: Best WER < 20% on median condition
median_wers = df_asr.groupby("condition")["metrics.wer"].median()
best_median_wer = median_wers.min()
print(f"Best median WER: {best_median_wer:.1%}")
assert best_median_wer < 0.20, f"GATE FAILED: Best median WER {best_median_wer:.1%} >= 20%"

# Gate 2: Embedding purity > 0.60
emb_runs = mlflow.search_runs(experiment_names=["S06_Embedding_Bakeoff"])
df_emb = pd.DataFrame(emb_runs)
best_purity = df_emb["metrics.purity"].max()
print(f"Best purity: {best_purity:.3f}")
assert best_purity > 0.60, f"GATE FAILED: Best purity {best_purity:.3f} <= 0.60"

print("ALL GATES PASSED")
```

---

### 6. Dependency & Environment Configuration

**Container Environment (for bake-off scripts):**
```bash
# Use base-gpu image
docker run --rm --gpus all -v $(pwd):/workspace lis/base-gpu:latest \
  bash -c "cd /workspace && python scripts/s06_asr_bakeoff.py"
```

**Required Python Packages (in base-gpu):**
- faster-whisper 1.1.0
- ctranslate2 4.8.2
- nemo-toolkit (for Parakeet/Canary)
- sentence-transformers 3.2.0
- bertopic 0.16.0
- jiwer 3.0.4
- mlflow 2.16.2

**Environment Variables:**
```bash
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
HF_HOME=/models/huggingface
CUDA_VISIBLE_DEVICES=0
PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128,expandable_segments:True
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Verification | Threshold |
|---------|------|--------------|-----------|
| T06.1 | V | Best ASR WER on median condition | **< 20%** (GATE) |
| T06.2 | V | Clustering purity (Qwen3-0.6B) | **> 0.60** (GATE) |
| T06.3 | V | Worst-condition WER recorded | If >35% -> capture issue |
| T06.4 | V | Pairwise ASR disagreement vs error correlation | Negative correlation |
| T06.5 | M | `config/models.yaml` frozen with decisions | File committed |
| T06.6 | I | All 4 models load sequentially without OOM | `torch.cuda.max_memory_allocated() < 4GB` |

**Verification Commands:**
```bash
# 1. Run bake-off (takes 8-12 hours on 4GB GPU)
docker run --rm --gpus all -v $(pwd):/workspace -v lis-models:/models \
  -e MLFLOW_TRACKING_URI=http://host.docker.internal:5000 \
  lis/base-gpu:latest bash -c "cd /workspace && python scripts/s06_run_all.py"

# 2. Check gates
docker run --rm --gpus all -v $(pwd):/workspace lis/base-gpu:latest \
  python scripts/s06_check_gates.py

# 3. Verify config frozen
cat config/models.yaml

# 4. View MLflow UI
open https://mlflow.lis.local
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| **Gate T06.1 FAILS (WER >= 20%)** | `s06_check_gates.py` exits 1 | **PROJECT HALTS** — fix audio capture (better mic, placement, room treatment) before any downstream work |
| **Gate T06.2 FAILS (purity <= 0.60)** | `s06_check_gates.py` exits 1 | Try different UMAP n_neighbors (5-50), HDBSCAN min_cluster_size (3-15); reduce embedding dim via PCA |
| OOM during bake-off | Container killed / CUDA OOM | Reduce batch_size to 1; increase swap; process one condition at a time |
| Canary/Parakeet not loading | ImportError / load fails | Install nemo-toolkit; check transformers>=4.44; use HF hub IDs |
| MLflow tracking fails | Connection refused | Use local file tracking: `mlflow.set_tracking_uri("file:///workspace/mlruns")` |
| Disagreement analysis shows no correlation | `disagreement_rate` ~ random | Check alignment method; ensure same audio segments compared |
| Results not reproducible | Re-run gives different WER | Fix random seeds; deterministic CUDA: `torch.use_deterministic_algorithms(True)` |
