# S60 — OCR Services & Confidence
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement OCR services using PaddleOCR-VL for printed/PDF content, a VLM-OCR model for handwriting/boards (benchmarked at this stage), with OpenCV/Pillow preprocessing (deskew, perspective correct, de-glare) before OCR, confidence scoring with low-confidence flags, and two-model disagreement as an additional confidence signal. The uploaded image is always retained in notes regardless of OCR success.

**Component Boundaries:**
- **Allowed:** `src/services/ocr/`, `src/services/ocr/preprocess.py`, `src/services/ocr/paddle_ocr.py`, `src/services/ocr/vlm_ocr.py`, `src/services/ocr/confidence.py`, `src/services/ocr/pipeline.py`, `src/api/routes/ocr.py`, `tests/test_ocr.py`, `tests/test_preprocess.py`, `tests/test_ocr_confidence.py`
- **Off-limits:** Upload handling (S59), image retrieval (S62), image generation (S63), visual assembly (S64)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| PaddleOCR | 2.9.x | Printed text and PDF OCR |
| PaddlePaddle | 2.6.x | Inference backend for PaddleOCR |
| OpenCV | 4.10.x | Image preprocessing (deskew, perspective, de-glare) |
| Pillow | 11.x | Image preprocessing and format handling |
| PyTorch | 2.5.x | VLM-OCR model inference |
| transformers | 4.45.x | VLM model loading |
| FastAPI | 0.141.1 | OCR trigger endpoints |
| SQLAlchemy | 2.0.52 | OCR result persistence |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**OCR Processing State Machine:**
```
raw_image → preprocess → preprocessed → ocr_inference → text_extracted → confidence_scored → complete
                                        ↓ (dual model)
                                    disagreement_check → low_confidence_flagged
```

**OCR Service Type Enum:**
```python
# src/services/ocr/models.py
from enum import Enum


class OCRServiceType(str, Enum):
    PADDLE_OCR = "paddle_ocr"  # Printed/PDF text
    VLM_OCR = "vlm_ocr"  # Handwriting/boards
    DOTS_OCR = "dots_ocr"  # Fallback


class OCRConfidenceLevel(str, Enum):
    HIGH = "high"  # ≥ 0.85
    MEDIUM = "medium"  # 0.60 – 0.84
    LOW = "low"  # < 0.60
    DISAGREEMENT = "disagreement"  # Models disagree significantly
```

**Pydantic Schemas:**
```python
# src/services/ocr/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class OCRResult(BaseModel):
    id: UUID
    upload_id: UUID
    service_used: OCRServiceType
    extracted_text: str = Field(..., max_length=50000)
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: OCRConfidenceLevel
    is_low_confidence: bool = False
    disagreement_flag: bool = False
    paddle_text: str | None = None
    vlm_text: str | None = None
    paddle_confidence: float | None = None
    vlm_confidence: float | None = None
    preprocessing_applied: list[str] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class OCRRequest(BaseModel):
    upload_id: UUID
    service: OCRServiceType | None = None  # Auto-detect if None


class OCRBatchRequest(BaseModel):
    upload_ids: list[UUID] = Field(..., min_length=1, max_length=50)


class PreprocessingConfig(BaseModel):
    enable_deskew: bool = True
    enable_perspective_correct: bool = True
    enable_deglare: bool = True
    enable_binarize: bool = False
    deskew_angle_threshold: float = 0.5  # degrees
    perspective_margin: float = 0.02


class OCRConfig(BaseModel):
    paddle_lang: str = "en"
    paddle_use_gpu: bool = True
    vlm_model_name: str = "microsoft/Florence-2-large"
    vlm_max_tokens: int = 2048
    confidence_threshold_high: float = 0.85
    confidence_threshold_low: float = 0.60
    disagreement_threshold: float = 0.3  # max acceptable difference between model confidences
    dots_ocr_url: str = "http://dots-ocr:8080/v1/ocr"
```

**OCR Confidence Scoring:**
```python
# src/services/ocr/confidence.py
class ConfidenceScorer:
    def score(
        self,
        paddle_result: tuple[str, float] | None,
        vlm_result: tuple[str, float] | None,
    ) -> OCRResult:
        """Score OCR result with disagreement detection."""
        # If only one model ran, use its confidence directly
        # If both ran:
        #   - agreement (diff < threshold): use average confidence
        #   - disagreement (diff >= threshold): flag, use lower confidence
        ...
```

**State Transition Rules:**
- `raw_image` → `preprocessing`: Image submitted to preprocessing pipeline
- `preprocessing` → `preprocessed`: Deskew, perspective correct, de-glare applied
- `preprocessed` → `ocr_inference`: Preprocessed image sent to OCR service(s)
- `ocr_inference` → `text_extracted`: OCR returns text + per-word confidences
- `text_extracted` → `confidence_scored`: Overall confidence computed; disagreement checked
- `confidence_scored` → `complete`: OCR result stored; low-confidence flagged if applicable
- Any state → `failed`: OCR error; image retained in notes, text marked as unavailable

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create OCR Pydantic models in `src/services/ocr/models.py` | Import succeeds, mypy passes |
| 2 | Create `src/services/ocr/preprocess.py` — OpenCV/Pillow preprocessing | T60.4: preprocessing improves accuracy |
| 3 | Create `src/services/ocr/paddle_ocr.py` — PaddleOCR-VL wrapper | Printed-page OCR accuracy > 0.95 |
| 4 | Create `src/services/ocr/vlm_ocr.py` — VLM-OCR wrapper | Board photo OCR measured honestly |
| 5 | Create `src/services/ocr/confidence.py` — confidence scoring and disagreement | T60.6: disagreement flags low confidence |
| 6 | Create `src/services/ocr/pipeline.py` — orchestrates preprocess → OCR → score | Pipeline runs end-to-end |
| 7 | Create `src/api/routes/ocr.py` — OCR trigger endpoint | API returns OCR results |
| 8 | Write integration tests | All T60.x tests pass |

**Atomic Sub-tasks:**
1. OCR Pydantic models and config
2. Image preprocessing service (deskew, perspective, de-glare)
3. PaddleOCR-VL service wrapper
4. VLM-OCR service wrapper
5. Confidence scoring with disagreement detection
6. OCR pipeline orchestrator
7. OCR API endpoint
8. dots.ocr fallback integration
9. Integration test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| PaddleOCR fails to load model | Fall back to dots.ocr; log warning |
| VLM-OCR OOM on GPU | Fall back to PaddleOCR; log warning |
| Image too blurry for any OCR | Return empty text with confidence=0; image retained |
| PDF page extraction fails | Skip that page; log warning; process remaining |
| OCR returns empty text | Set `confidence=0`, `confidence_level=LOW`; image retained |
| Both models fail | Mark as `failed`; image still stored in notes |
| Preprocessing crashes (corrupted image) | Skip preprocessing; OCR on raw image; log warning |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: OCR service selection (PaddleOCR, VLM-OCR, dots.ocr)
- Pipeline pattern: preprocess → OCR → confidence score
- Adapter pattern: Wrap each OCR service behind a common `OCRProvider` interface
- Fallback chain: VLM-OCR → PaddleOCR → dots.ocr

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`PaddleOCRProvider`, `VLMOCRProvider`, `ConfidenceScorer`)
- Files: snake_case (`paddle_ocr.py`, `vlm_ocr.py`, `confidence.py`)
- Functions: snake_case (`preprocess_image`, `run_ocr`, `score_confidence`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- UUID type hints for all ID parameters
- OCR confidence always `float` in range `[0.0, 1.0]`

---

### 5. API & Interface Contracts

**FastAPI Endpoints:**
```yaml
POST   /api/v1/ocr/run                   → 200 OCRResult
POST   /api/v1/ocr/batch                 → 200 list[OCRResult]
GET    /api/v1/ocr/{upload_id}           → 200 OCRResult
GET    /api/v1/ocr/{upload_id}/text      → 200 { text: str, confidence: float }
```

**Mock Request/Response Payloads:**
```json
// POST /api/v1/ocr/run
// Request:
{
  "upload_id": "770e8400-e29b-41d4-a716-446655440002",
  "service": null
}

// Response 200:
{
  "id": "990e8400-e29b-41d4-a716-446655440004",
  "upload_id": "770e8400-e29b-41d4-a716-446655440002",
  "service_used": "paddle_ocr",
  "extracted_text": "Gradient descent is an iterative optimization algorithm...",
  "confidence": 0.92,
  "confidence_level": "high",
  "is_low_confidence": false,
  "disagreement_flag": false,
  "paddle_text": "Gradient descent is an iterative optimization algorithm...",
  "vlm_text": null,
  "paddle_confidence": 0.92,
  "vlm_confidence": null,
  "preprocessing_applied": ["deskew", "deglare"],
  "created_at": "2026-09-12T10:30:05Z"
}

// Response 200 (low confidence / disagreement):
{
  "id": "aa0e8400-e29b-41d4-a716-446655440005",
  "upload_id": "770e8400-e29b-41d4-a716-446655440002",
  "service_used": "vlm_ocr",
  "extracted_text": "This text may be inaccurate...",
  "confidence": 0.45,
  "confidence_level": "low",
  "is_low_confidence": true,
  "disagreement_flag": true,
  "paddle_text": "Different text from paddle...",
  "vlm_text": "This text may be inaccurate...",
  "paddle_confidence": 0.72,
  "vlm_confidence": 0.45,
  "preprocessing_applied": ["deskew", "perspective_correct"],
  "created_at": "2026-09-12T10:30:10Z"
}

// POST /api/v1/ocr/batch
// Request:
{
  "upload_ids": [
    "770e8400-e29b-41d4-a716-446655440002",
    "880e8400-e29b-41d4-a716-446655440003"
  ]
}

// Response 200:
[
  { "id": "...", "upload_id": "...", "confidence": 0.92, ... },
  { "id": "...", "upload_id": "...", "confidence": 0.38, "is_low_confidence": true, ... }
]
```

**OCR Provider Interface:**
```python
# src/services/ocr/provider.py
from abc import ABC, abstractmethod


class OCRProvider(ABC):
    @abstractmethod
    async def run(self, image_path: str, lang: str = "en") -> tuple[str, float]:
        """Run OCR on image, return (text, confidence)."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider's model is loaded and GPU available."""
        ...
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `OCR_PADDLE_GPU` | bool | Use GPU for PaddleOCR | `true` |
| `OCR_VLM_MODEL` | string | VLM model name | `microsoft/Florence-2-large` |
| `OCR_VLM_GPU` | bool | Use GPU for VLM-OCR | `true` |
| `OCR_DOTS_URL` | string | dots.ocr fallback URL | `http://dots-ocr:8080/v1/ocr` |
| `OCR_CONFIDENCE_HIGH` | float | High confidence threshold | `0.85` |
| `OCR_CONFIDENCE_LOW` | float | Low confidence threshold | `0.60` |
| `OCR_DISAGREEMENT_THRESHOLD` | float | Max acceptable model confidence diff | `0.3` |

**Third-Party Integration Contracts:**
- PaddleOCR: Printed text recognition; requires PaddlePaddle backend
- transformers: VLM model loading (Florence-2 or similar)
- OpenCV: Image preprocessing (deskew, perspective transform, contrast enhancement)
- dots.ocr: Fallback OCR microservice (HTTP API)

**Version Pins:**
- `paddleocr` pinned in `pyproject.toml`
- `paddlepaddle-gpu` pinned in `pyproject.toml`
- `opencv-python-headless` pinned in `pyproject.toml`
- `transformers` pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T60.1 | V | `pytest tests/test_ocr.py::test_printed_accuracy -v` | Printed-page OCR accuracy > 0.95 on test set |
| T60.2 | V | `pytest tests/test_ocr.py::test_board_accuracy -v` | Board-photo OCR accuracy measured and published honestly |
| T60.3 | I | `pytest tests/test_ocr.py::test_low_confidence_flag -v` | Low-confidence extraction flagged, not presented as authoritative |
| T60.4 | V | `pytest tests/test_preprocess.py::test_preprocessing_improves -v` | Preprocessing measurably improves accuracy vs raw input |
| T60.5 | I | `pytest tests/test_ocr.py::test_image_retained -v` | Uploaded image retained in notes regardless of OCR success |
| T60.6 | I | `pytest test_ocr.py::test_disagreement_flag -v` | OCR model disagreement raises low-confidence flag |

**Test Case Details (Given/When/Then):**

**T60.1 — Printed-page OCR accuracy > 0.95**
- **Given:** a test set of 100 printed textbook page images with ground-truth text
- **When:** PaddleOCR-VL processes each image
- **Then:** character-level accuracy > 0.95 across the test set; results logged with per-image accuracy

**T60.2 — Board-photo OCR accuracy measured honestly**
- **Given:** a test set of 50 whiteboard/chalkboard photos with ground-truth text
- **When:** VLM-OCR processes each image
- **Then:** accuracy is measured and published as a metric; no inflated claims; accuracy level clearly documented as "best-effort" in response metadata

**T60.3 — Low-confidence extraction flagged**
- **Given:** a blurry board photo where OCR confidence is 0.42
- **When:** OCR pipeline processes the image
- **Then:** result has `is_low_confidence=true`; `confidence_level="low"`; text is still stored but marked as unreliable; UI displays a warning banner

**T60.4 — Preprocessing improves accuracy**
- **Given:** 20 skewed/de-glared images with known ground truth
- **When:** OCR runs on both raw and preprocessed versions
- **Then:** preprocessed accuracy is measurably higher than raw accuracy; improvement logged as a metric

**T60.5 — Image retained regardless of OCR success**
- **Given:** a board photo where OCR returns empty text (confidence=0)
- **When:** OCR pipeline completes
- **Then:** the original image is still stored in `note_assets`; `source_type='upload'`; the image is visible in the note view even though no text was extracted

**T60.6 — Disagreement raises low-confidence flag**
- **Given:** a handwritten note image where PaddleOCR confidence=0.72 and VLM-OCR confidence=0.45
- **When:** both models process the image and confidence is scored
- **Then:** `disagreement_flag=true`; `confidence_level="disagreement"`; the lower confidence is used as the overall score; both model outputs stored for audit

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- PaddleOCR GPU memory: if another service (S63 image generation) is using GPU, PaddleOCR may OOM — enforce VRAM budget from S02
- VLM-OCR (Florence-2) requires specific transformers version — pin strictly
- Perspective correction may fail on images with no detectable document edges — fall back to no correction
- De-glare may remove legitimate dark text on light background — apply conservatively
- dots.ocr fallback URL may be unreachable — handle timeout gracefully
- OCR accuracy metric must be computed on a fixed test set, not ad hoc samples

**Fallback Instructions:**
- If PaddleOCR GPU unavailable: fall back to CPU mode; log warning; accuracy may decrease
- If VLM-OCR OOM: fall back to PaddleOCR; log warning
- If PaddleOCR fails: fall back to dots.ocr; log warning
- If all OCR fails: mark result as `failed`; image still retained in notes; text marked as unavailable
- If preprocessing crashes: skip preprocessing; OCR on raw image; log warning

**Rollback Procedure:**
- Disable OCR: feature flag `OCR_ENABLED=false`
- OCR results are additive — removing them doesn't break notes
- Database migration is additive (OCR columns on `note_assets`)
- Image files remain in storage regardless of OCR status

---

### 9. Observability (if applicable)

**Metrics Added:**
- `ocr_requests_total`: counter of OCR requests (labels: service, confidence_level)
- `ocr_accuracy_printed`: gauge of printed-page OCR accuracy (updated per test run)
- `ocr_accuracy_board`: gauge of board-photo OCR accuracy
- `ocr_confidence_distribution`: histogram of OCR confidence scores
- `ocr_preprocessing_improvement`: gauge of accuracy improvement from preprocessing
- `ocr_disagreements_total`: counter of model disagreements detected
- `ocr_low_confidence_total`: counter of low-confidence results
- `ocr_latency_seconds`: histogram of OCR processing time (labels: service)
- `ocr_fallback_total`: counter of fallback activations

**Tracing/Logging:**
- Span: `ocr.process` with child spans for `ocr.preprocess`, `ocr.paddle`, `ocr.vlm`, `ocr.confidence`
- Log: INFO on OCR completion with service, confidence, text length
- Log: WARN on low-confidence result with confidence score
- Log: WARN on model disagreement with both model outputs
- Log: ERROR on OCR failure with error details and fallback activation

**Alerts:**
- Printed-page OCR accuracy drops below 0.90: investigate model or preprocessing
- Board-photo OCR accuracy drops below 0.30: investigate VLM model or image quality
- Disagreement rate > 20%: investigate model consistency
- Fallback activation rate > 10%: investigate primary model availability

---

### 10. Exit Checklist

- [ ] All tests pass (T60.1–T60.6)
- [ ] Printed-page OCR accuracy > 0.95 (T60.1)
- [ ] Board-photo OCR accuracy measured and published honestly (T60.2)
- [ ] Low-confidence results flagged, not presented as authoritative (T60.3)
- [ ] Preprocessing measurably improves accuracy (T60.4)
- [ ] Uploaded image retained in notes regardless of OCR success (T60.5)
- [ ] Model disagreement raises low-confidence flag (T60.6)
- [ ] OCR provider interface implemented for PaddleOCR, VLM-OCR, and dots.ocr
- [ ] Confidence scoring with disagreement detection functional
