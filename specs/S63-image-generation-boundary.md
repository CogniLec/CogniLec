# S63 — Image Generation & FR-4.9 Boundary (HARD GATE)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Implement FLUX.1-schnell image generation via `diffusers` in our own service, with the generation service's API accepting **no image parameter whatsoever** — a restricted image cannot reach the generator because there is no field to pass it in. Generation is driven solely by textual concept description. Outputs are labelled AI-generated and cached per `(subject, concept)`. A custom Semgrep rule in CI enforces the FR-4.9 copyright boundary structurally.

**⛔ HARD GATE:** This stage has three mandatory gate tests (T63.1, T63.2, T63.3) that must pass before the pipeline can proceed. The FR-4.9 boundary is enforced **structurally** (API schema has no image input field) and **by CI** (Semgrep rule fails CI if a code path from retrieval bytes to generator is created). Policy or prompt wording is insufficient.

**Component Boundaries:**
- **Allowed:** `src/services/image_generation/`, `src/services/image_generation/generator.py`, `src/services/image_generation/cache.py`, `src/services/image_generation/labeller.py`, `src/services/image_generation/schema.py`, `.semgrep/rules/fr49_boundary.yaml`, `tests/test_image_generation.py`, `tests/test_boundary.py`
- **Off-limits:** Image retrieval (S62), concept detection (S61), visual assembly (S64), any code path that passes image bytes to the generator

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| diffusers | 0.30.x | FLUX.1-schnell inference |
| torch | 2.5.x | GPU inference backend |
| transformers | 4.45.x | Text encoder for FLUX |
| accelerate | 0.34.x | GPU memory management |
| Semgrep | 1.88.x | Static analysis for FR-4.9 boundary |
| FastAPI | 0.141.1 | Generation API |
| SQLAlchemy | 2.0.52 | Cache persistence |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Generation State Machine:**
```
concept_received → cache_check → cache_hit → return_cached
                         ↓
                    cache_miss → text_encode → generate_image → label_ai_generated
                         ↓                                              ↓
                    concept_cache_store ← ← ← ← ← ← ← ← ← ← ← ← ←
```

**⛔ FR-4.9 Boundary Enforcement:**
```
┌─────────────────────────────────────────────────────────────┐
│  GENERATION SERVICE API SCHEMA                              │
│                                                             │
│  GenerateRequest {                                          │
│      concept_description: str    ← TEXT ONLY                │
│      subject_id: UUID                                         │
│      style_preset: str | None                                │
│      width: int = 512                                        │
│      height: int = 512                                       │
│  }                                                          │
│                                                             │
│  ⛔ NO image parameter exists                                │
│  ⛔ NO image_url parameter exists                            │
│  ⛔ NO reference_image parameter exists                      │
│  ⛔ NO input_bytes parameter exists                          │
│                                                             │
│  It is STRUCTURALLY IMPOSSIBLE to pass a copyrighted        │
│  image to this service. The field does not exist.           │
└─────────────────────────────────────────────────────────────┘
```

**Pydantic Schemas:**
```python
# src/services/image_generation/schema.py
from pydantic import BaseModel, Field, model_validator
from uuid import UUID
from datetime import datetime
from enum import Enum


class GenerationStyle(str, Enum):
    DIAGRAM = "diagram"
    ILLUSTRATION = "illustration"
    SCHEMATIC = "schematic"
    NATURAL = "natural"


class GenerateRequest(BaseModel):
    """Request to generate an image from text description ONLY.

    ⛔ FR-4.9: This schema intentionally has NO image parameter.
    A copyrighted image CANNOT be passed to the generation service.
    This is enforced by:
    1. Pydantic schema validation (no image field exists)
    2. Semgrep rule (T63.3 — CI gate)
    3. API schema validation (OpenAPI spec has no image parameter)
    """

    concept_description: str = Field(..., min_length=10, max_length=2000)
    subject_id: UUID
    style_preset: GenerationStyle = GenerationStyle.ILLUSTRATION
    width: int = Field(default=512, ge=256, le=1024)
    height: int = Field(default=512, ge=256, le=1024)
    seed: int | None = None  # For reproducibility

    @model_validator(mode="after")
    def no_image_parameter(self):
        """Structural guard: ensure no image-related fields exist."""
        image_fields = [f for f in self.model_fields if "image" in f.lower()]
        if image_fields:
            raise ValueError(f"FR-4.9 violation: image fields not allowed: {image_fields}")
        return self


class GeneratedImage(BaseModel):
    id: UUID
    concept_description: str
    image_url: str
    storage_path: str
    width: int
    height: int
    seed: int | None = None
    is_ai_generated: bool = True  # AC-17, FR-4.10 — always True
    ai_label: str = "AI-generated illustration"
    style_preset: GenerationStyle
    subject_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class GenerationResult(BaseModel):
    generated: GeneratedImage | None = None
    cached: bool = False
    cache_hit_id: UUID | None = None
    generation_time_ms: int | None = None
    concept_description: str


class ConceptCache(BaseModel):
    id: UUID
    subject_id: UUID
    concept_hash: str  # SHA-256 of normalized concept description
    generated_image_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
```

**SQLAlchemy Model — Generation Cache:**
```sql
CREATE TABLE image_generation_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id      UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    concept_hash    VARCHAR(64) NOT NULL,  -- SHA-256 of normalized concept
    generated_image_id UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subject_id, concept_hash)
);

CREATE INDEX idx_image_gen_cache_subject ON image_generation_cache(subject_id);
CREATE INDEX idx_image_gen_cache_hash ON image_generation_cache(concept_hash);
```

**AI-Generated Labelling (AC-17, FR-4.10):**
```python
# src/services/image_generation/labeller.py
class AIGeneratedLabeller:
    """Ensure every generated image is labelled as AI-generated."""

    def apply_label(self, image: GeneratedImage) -> GeneratedImage:
        """Apply AI-generated label to image metadata and embed in EXIF."""
        image.is_ai_generated = True
        image.ai_label = "AI-generated illustration"
        # Also embed label in EXIF/metadata of the image file itself
        ...
        return image
```

**State Transition Rules:**
- `concept_received` → `cache_check`: Normalize concept text; compute SHA-256 hash
- `cache_check` → `cache_hit`: Hash found in `image_generation_cache`; return cached image
- `cache_check` → `cache_miss`: Hash not found; proceed to generation
- `cache_miss` → `text_encode`: Concept description encoded by FLUX text encoder
- `text_encode` → `generate_image`: FLUX.1-schnell generates image from text encoding ONLY
- `generate_image` → `label_ai_generated`: AI-generated label applied (FR-4.10)
- `label_ai_generated` → `concept_cache_store`: Image cached for future requests
- Any state → `failed`: Generation error; log; concept remains unresolved

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create generation schema with FR-4.9 structural guard | T63.1: API has no image input parameter |
| 2 | Create `.semgrep/rules/fr49_boundary.yaml` | T63.3: Semgrep rule defined |
| 3 | Create `src/services/image_generation/generator.py` | FLUX.1-schnell generates from text |
| 4 | Create `src/services/image_generation/labeller.py` | T63.5: every image labelled AI-generated |
| 5 | Create `src/services/image_generation/cache.py` | T63.6: repeated concept served from cache |
| 6 | Verify no retrieval bytes reach generator | T63.2: end-to-end trace shows no image path |
| 7 | Verify no similarity score for restricted candidates | T63.4: licence check precedes scoring |
| 8 | Test user rejection flow | T63.8: rejection triggers regeneration/removal |
| 9 | Human evaluation of generated quality | T63.7: useful and stylistically consistent |
| 10 | Run Semgrep in CI | T63.3: CI gate passes |
| 11 | Write integration tests | All T63.x tests pass |

**Atomic Sub-tasks:**
1. Generation Pydantic schema with FR-4.9 structural guard
2. Semgrep rule for FR-4.9 boundary
3. FLUX.1-schnell generator service
4. AI-generated labeller (metadata + EXIF embedding)
5. Concept cache (SHA-256 hash → generated image)
6. Generation API endpoint
7. User rejection/regeneration flow
8. CI integration for Semgrep gate
9. Integration test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| FLUX OOM on GPU | Fall back to text diagram; log warning; do NOT use copyrighted reference |
| Generation produces NSFW content | Reject; log; do not store; flag for review |
| Cache hash collision | Use full concept text as secondary key; log warning |
| Semgrep rule false positive | Investigate; update rule pattern if needed |
| User rejects generated image | Trigger regeneration with different seed; or remove (FR-4.12) |
| GPU unavailable | Return 503; suggest text diagram fallback |
| Generation exceeds time limit | Timeout; return error; concept remains unresolved |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: Generation backend (FLUX.1-schnell)
- Cache-aside pattern: Check cache before generation; store after
- Decorator pattern: Labeller wraps generated images with AI label
- Guard pattern: Schema validator enforces FR-4.9 at model level

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`FLUXGenerator`, `ConceptCache`, `AIGeneratedLabeller`)
- Files: snake_case (`generator.py`, `cache.py`, `labeller.py`, `schema.py`)
- Functions: snake_case (`generate_image`, `check_cache`, `apply_label`)
- Constants: UPPER_SNAKE_CASE (`GENERATION_TIMEOUT`, `CACHE_TTL`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- `GenerateRequest` schema validated by Pydantic and Semgrep
- `is_ai_generated` is always `True` — never set to `False`

---

### 5. API & Interface Contracts

**⛔ Generation API — No Image Parameter:**
```yaml
POST   /api/v1/generate/image           → 200 GenerationResult
GET    /api/v1/generate/cache/{hash}    → 200 GeneratedImage
DELETE /api/v1/generate/image/{id}      → 204  # User rejection (FR-4.12)
POST   /api/v1/generate/image/{id}/regenerate → 200 GenerationResult
```

**OpenAPI Schema (FR-4.9 — no image parameter):**
```yaml
paths:
  /api/v1/generate/image:
    post:
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/GenerateRequest'
      responses:
        '200':
          description: Generated image

components:
  schemas:
    GenerateRequest:
      type: object
      required:
        - concept_description
        - subject_id
      properties:
        concept_description:
          type: string
          minLength: 10
          maxLength: 2000
        subject_id:
          type: string
          format: uuid
        style_preset:
          type: string
          enum: [diagram, illustration, schematic, natural]
          default: illustration
        width:
          type: integer
          minimum: 256
          maximum: 1024
          default: 512
        height:
          type: integer
          minimum: 256
          maximum: 1024
          default: 512
        seed:
          type: integer
          nullable: true
      # ⛔ NO image parameter
      # ⛔ NO image_url parameter
      # ⛔ NO reference_image parameter
      # ⛔ NO input_bytes parameter
```

**Mock Request/Response Payloads:**
```json
// POST /api/v1/generate/image
// Request:
{
  "concept_description": "Cross-section diagram of the human heart showing four chambers, valves, and major blood vessels",
  "subject_id": "550e8400-e29b-41d4-a716-446655440000",
  "style_preset": "illustration",
  "width": 512,
  "height": 512,
  "seed": 42
}

// Response 200:
{
  "generated": {
    "id": "770e8400-e29b-41d4-a716-446655440002",
    "concept_description": "Cross-section diagram of the human heart...",
    "image_url": "/storage/generated/770e8400.png",
    "storage_path": "generated/770e8400.png",
    "width": 512,
    "height": 512,
    "seed": 42,
    "is_ai_generated": true,
    "ai_label": "AI-generated illustration",
    "style_preset": "illustration",
    "subject_id": "550e8400-e29b-41d4-a716-446655440000",
    "created_at": "2026-09-12T10:30:00Z"
  },
  "cached": false,
  "cache_hit_id": null,
  "generation_time_ms": 3200,
  "concept_description": "Cross-section diagram of the human heart..."
}

// Response 200 (cache hit):
{
  "generated": null,
  "cached": true,
  "cache_hit_id": "770e8400-e29b-41d4-a716-446655440002",
  "generation_time_ms": null,
  "concept_description": "Cross-section diagram of the human heart..."
}
```

**Semgrep Rule (FR-4.9 Boundary):**
```yaml
# .semgrep/rules/fr49_boundary.yaml
rules:
  - id: fr49-no-image-to-generator
    patterns:
      - pattern: |
          $GEN = Generator(...)
          ...
          $GEN.generate(image=$IMG, ...)
      - pattern-not: |
          $GEN = Generator(...)
          ...
          $GEN.generate(concept=$CONCEPT, ...)
    message: >
      FR-4.9 VIOLATION: Image bytes cannot be passed to the generator.
      The generator API accepts only text descriptions.
      See ADR-008 and S63 specification.
    languages: [python]
    severity: ERROR
    metadata:
      category: security
      technology: [python]
      confidence: HIGH
      references:
        - docs/adrs/008-copyright-safe-visual-enrichment.md
        - specs/S63-image-generation-boundary.md

  - id: fr49-no-retrieval-to-generator
    pattern-either:
      - pattern: |
          $BYTES = $SOURCE.get_image(...)
          ...
          $GENERATOR.generate(..., image=$BYTES, ...)
      - pattern: |
          $IMG = $RETRIEVAL.retrieve(...)
          ...
          $GENERATOR.generate(..., image=$IMG, ...)
    message: >
      FR-4.9 VIOLATION: Retrieval output cannot flow to generator input.
      This creates a path from copyrighted images to the generator.
      See ADR-008.
    languages: [python]
    severity: ERROR
    metadata:
      category: security
      confidence: HIGH
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `GENERATION_GPU_ENABLED` | bool | Use GPU for image generation | `true` |
| `FLUX_MODEL_NAME` | string | FLUX model identifier | `black-forest-labs/FLUX.1-schnell` |
| `GENERATION_TIMEOUT_SEC` | int | Max generation time | `30` |
| `CACHE_TTL_HOURS` | int | Concept cache TTL | `720` (30 days) |
| `GENERATION_STORAGE_PATH` | string | Storage path for generated images | `./generated` |
| `SEMGREP_RULES_PATH` | string | Path to Semgrep rules | `.semgrep/rules/` |

**Third-Party Integration Contracts:**
- diffusers: FLUX.1-schnell inference pipeline
- torch: GPU inference backend
- accelerate: GPU memory management and device mapping
- Semgrep: Static analysis for FR-4.9 boundary enforcement

**Version Pins:**
- `diffusers` pinned in `pyproject.toml`
- `torch` pinned in `pyproject.toml` (CUDA-specific wheel)
- `accelerate` pinned in `pyproject.toml`
- `semgrep` pinned in CI pipeline

---

### 7. Definition of Done & Verification

**⛔ MANDATORY GATE TESTS — Must pass before pipeline proceeds:**

| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T63.1 | S | `pytest tests/test_boundary.py::test_no_image_parameter -v` | **GATE: the generation service API has no image input parameter** |
| T63.2 | S | `pytest tests/test_boundary.py::test_no_retrieval_to_generator -v` | **GATE: restricted candidate image never reaches generator** |
| T63.3 | S | `semgrep --config .semgrep/rules/fr49_boundary.yaml src/` | **GATE: Semgrep rule fails CI when code creates path from retrieval to generator** |

**Additional Tests:**

| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T63.4 | I | `pytest tests/test_image_generation.py::test_no_score_for_restricted -v` | No similarity score computed for restricted candidate |
| T63.5 | I | `pytest tests/test_image_generation.py::test_ai_label -v` | Every generated image labelled AI-generated |
| T63.6 | I | `pytest tests/test_image_generation.py::test_cache_hit -v` | Repeated concept served from cache |
| T63.7 | M | Human evaluation on 20 generated images | Useful and stylistically consistent within subject |
| T63.8 | I | `pytest tests/test_image_generation.py::test_user_rejection -v` | User rejection triggers regeneration or removal |

**Test Case Details (Given/When/Then):**

**T63.1 — ⛔ GATE: API has no image input parameter**
- **Given:** the `GenerateRequest` Pydantic model and OpenAPI schema
- **When:** schema is inspected programmatically (check `model_fields` and OpenAPI spec)
- **Then:** no field named `image`, `image_url`, `reference_image`, `input_bytes`, or any image-related field exists; OpenAPI spec confirms no image parameter in POST `/api/v1/generate/image`

**T63.2 — ⛔ GATE: Restricted candidate never reaches generator**
- **Given:** a retrieved image from S62 with `licence=CC-BY-NC-ND` (restricted)
- **When:** the full enrichment pipeline runs (concept → retrieval → generation)
- **Then:** the restricted image is never passed to the generator; traced through the code path: retrieval output → licence check → REJECTED before scoring → generator receives only text description; no image bytes arrive at the generator

**T63.3 — ⛔ GATE: Semgrep rule fails CI on boundary violation**
- **Given:** a code change that creates a path from `RetrievalService.retrieve()` output bytes to `FLUXGenerator.generate()` input
- **When:** `semgrep --config .semgrep/rules/fr49_boundary.yaml src/` runs in CI
- **Then:** Semgrep exits with code 1 (failure); CI pipeline fails; the violation is reported with file and line number

**T63.4 — No similarity score computed for restricted candidate**
- **Given:** a concept description and a restricted image candidate
- **When:** the pipeline processes the candidate
- **Then:** licence check happens BEFORE any CLIP or similarity scoring; the restricted candidate is rejected at licence check; no compute wasted on scoring; FR-4.3 ordering enforced

**T63.5 — Every generated image labelled AI-generated**
- **Given:** FLUX generates an image for a concept
- **When:** the image is stored and returned
- **Then:** `is_ai_generated=true`; `ai_label="AI-generated illustration"`; EXIF metadata contains AI-generated tag; client displays "AI-generated" badge (AC-17, FR-4.10)

**T63.6 — Repeated concept served from cache**
- **Given:** a concept "Anatomy of the human heart" was previously generated for subject X
- **When:** the same concept is requested again for subject X
- **Then:** cache hit; no GPU inference; `cached=true` in response; same image returned; `generation_time_ms` is null or very low (< 100ms)

**T63.7 — Generated images useful and stylistically consistent**
- **Given:** 20 concepts from the same subject (e.g., biology)
- **When:** FLUX generates images for all 20
- **Then:** human evaluators rate each image; average score ≥ 3.5/5 on usefulness; stylistic consistency across the subject is maintained; results logged

**T63.8 — User rejection triggers regeneration or removal**
- **Given:** a generated image with `id=X` for a concept
- **When:** user calls `DELETE /api/v1/generate/image/X` or `POST /api/v1/generate/image/X/regenerate`
- **Then:** on delete: image removed from `note_assets`, concept becomes unresolved; on regenerate: new image generated with different seed, old image replaced; FR-4.12 satisfied

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- ⛔ **CRITICAL:** If any code path is found that passes image bytes to the generator, the entire FR-4.9 boundary is compromised. Semgrep rule must catch this.
- FLUX.1-schnell requires significant GPU VRAM (~12GB) — enforce VRAM budget from S02
- Concept cache hash collisions are theoretically possible — use SHA-256 with full text as secondary key
- AI-generated label must be embedded in both metadata AND image file (EXIF) to be tamper-resistant
- Semgrep rule may need tuning to avoid false positives on unrelated patterns
- User rejection flow must handle in-progress generations gracefully

**Fallback Instructions:**
- If GPU unavailable: return 503; suggest text diagram fallback to client
- If FLUX OOM: reduce resolution; retry; log warning
- If generation timeout: return error; concept remains unresolved; text diagram attempted
- If Semgrep false positive: investigate; update rule pattern; do NOT disable rule
- If cache corrupted: delete cache entries; regenerate; log warning

**Rollback Procedure:**
- Disable image generation: feature flag `IMAGE_GENERATION_ENABLED=false`
- Generated images are additive — removing them doesn't break notes
- Cache entries can be truncated: `TRUNCATE TABLE image_generation_cache`
- Semgrep rule must NEVER be disabled — it's a security gate
- ⛔ The FR-4.9 boundary (no image parameter) is PERMANENT — cannot be rolled back

---

### 9. Observability (if applicable)

**Metrics Added:**
- `generation_requests_total`: counter of generation requests
- `generation_cache_hits_total`: counter of cache hits
- `generation_cache_misses_total`: counter of cache misses
- `generation_success_total`: counter of successful generations
- `generation_failure_total`: counter of failed generations
- `generation_latency_seconds`: histogram of generation time
- `generation_gpu_memory_bytes`: gauge of GPU memory usage
- `generation_rejections_total`: counter of user rejections (FR-4.12)

**Tracing/Logging:**
- Span: `generation.process` with child spans for `generation.cache_check`, `generation.inference`, `generation.label`, `generation.cache_store`
- Log: INFO on generation with concept hash, seed, timing
- Log: INFO on cache hit with concept hash
- Log: WARN on generation failure with error details
- Log: INFO on user rejection with image ID and action
- ⛔ Log: ERROR on ANY attempt to pass image to generator (should never happen)

**Alerts:**
- Generation failure rate > 5%: investigate GPU or model
- Cache hit rate < 20%: investigate cache TTL or concept normalization
- ⛔ Semgrep FR-4.9 violation detected: IMMEDIATE investigation — potential copyright breach
- GPU memory usage > 90%: investigate memory leak or concurrent generations

---

### 10. Exit Checklist

- [ ] **⛔ T63.1 passes — API has no image input parameter (HARD GATE)**
- [ ] **⛔ T63.2 passes — restricted image never reaches generator (HARD GATE)**
- [ ] **⛔ T63.3 passes — Semgrep rule enforces boundary in CI (HARD GATE)**
- [ ] No similarity score computed for restricted candidates (T63.4)
- [ ] Every generated image labelled AI-generated (T63.5)
- [ ] Repeated concepts served from cache (T63.6)
- [ ] Generated images useful and stylistically consistent (T63.7)
- [ ] User rejection triggers regeneration or removal (T63.8)
- [ ] FLUX.1-schnell generates images from text description only
- [ ] Concept cache implemented with SHA-256 hashing
- [ ] ⛔ FR-4.9 copyright boundary enforced structurally and by CI
