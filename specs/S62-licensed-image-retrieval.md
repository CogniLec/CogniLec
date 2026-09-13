# S62 — Licensed Image Retrieval & Scoring
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Query only licence-filtered image sources (Openverse, Wikimedia Commons, NASA/NIH/PMC/USGS, Open Clipart), compute a composite concept-match score per §9.4 (0.5·text-similarity + 0.5·CLIP alignment), accept at ≥ 0.50, and ensure every used image has a non-null `source_url` and `licence` recorded and displayed. General web image search is explicitly excluded.

**Component Boundaries:**
- **Allowed:** `src/services/image_retrieval/`, `src/services/image_retrieval/sources/`, `src/services/image_retrieval/scorer.py`, `src/services/image_retrieval/licence.py`, `src/services/image_retrieval/attribution.py`, `src/api/routes/images.py`, `tests/test_image_retrieval.py`, `tests/test_image_scorer.py`, `tests/test_licence.py`
- **Off-limits:** Image generation (S63), concept detection (S61), visual assembly (S64), general web search APIs

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| httpx | 0.27.x | Async HTTP client for image source APIs |
| CLIP (openai/clip-vit) | 1.0.x | Image-text alignment scoring |
| sentence-transformers | 3.x | Text similarity for composite scoring |
| Pillow | 11.x | Image decoding for CLIP |
| FastAPI | 0.141.1 | Image retrieval API |
| SQLAlchemy | 2.0.52 | Image metadata persistence |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Image Retrieval Flow:**
```
concept_description → query_build → source_queries (parallel)
    → raw_results → licence_filter → scored_results
    → threshold_filter (≥ 0.50) → accepted_images
    → attribution_capture → stored in note_assets
```

**Licence Category (enforced):**
```python
# src/services/image_retrieval/licence.py
from enum import Enum


class LicenceCategory(str, Enum):
    CC0 = "cc0"  # Public domain
    CC_BY = "cc-by"  # Attribution only
    CC_BY_SA = "cc-by-sa"  # Attribution + ShareAlike
    CC_BY_ND = "cc-by-nd"  # Attribution + NoDerivatives
    CC_BY_NC = "cc-by-nc"  # Attribution + NonCommercial
    CC_BY_NC_SA = "cc-by-nc-sa"  # Attribution + NC + SA
    CC_BY_NC_ND = "cc-by-nc-nd"  # Attribution + NC + ND
    PDM = "pdm"  # Public Domain Mark
    ODC_ODbL = "odc-odbl"  # Open Database License
    USGOV = "usgov"  # US Government work
    UNKNOWN = "unknown"  # Cannot verify — reject


class LicenceAcceptance(str, Enum):
    ACCEPTED = "accepted"  # Licence verified and acceptable
    REJECTED = "rejected"  # Licence not acceptable
    UNVERIFIABLE = "unverifiable"  # Cannot determine licence — reject
```

**Pydantic Schemas:**
```python
# src/services/image_retrieval/models.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class ImageSource(BaseModel):
    name: str  # "openverse", "wikimedia", "nasa", etc.
    base_url: str
    api_type: str  # "rest", "sparql"
    rate_limit_rpm: int = 60


class RetrievedImage(BaseModel):
    id: str  # Source-specific ID
    source: ImageSource
    source_url: str  # URL to the image on its source
    image_url: str  # Direct URL to the image file
    title: str
    licence: LicenceCategory
    licence_url: str | None = None
    author: str | None = None
    width: int | None = None
    height: int | None = None
    thumbnail_url: str | None = None


class ScoredImage(BaseModel):
    retrieved: RetrievedImage
    text_similarity: float = Field(..., ge=0.0, le=1.0)
    clip_alignment: float = Field(..., ge=0.0, le=1.0)
    composite_score: float = Field(..., ge=0.0, le=1.0)
    accepted: bool = False  # composite_score >= threshold


class ImageRetrievalResult(BaseModel):
    concept_description: str
    images_retrieved: int
    images_after_licence_filter: int
    images_after_score_filter: int
    accepted_images: list[ScoredImage]
    source_breakdown: dict[str, int]  # source_name → count
    best_match: ScoredImage | None = None


class ImageAsset(BaseModel):
    id: UUID
    note_section_id: UUID
    source_url: str  # MANDATORY — enforced by DB constraint
    licence: LicenceCategory  # MANDATORY — enforced by DB constraint
    licence_url: str | None = None
    author: str | None = None
    image_url: str
    thumbnail_url: str | None = None
    composite_score: float
    is_ai_generated: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AttributionDisplay(BaseModel):
    image_id: UUID
    source_url: str
    licence: LicenceCategory
    licence_url: str | None
    author: str | None
    attribution_text: str  # formatted attribution string
```

**Composite Scoring Formula (§9.4):**
```
composite_score = 0.5 * text_similarity + 0.5 * clip_alignment
```
- `text_similarity`: cosine similarity between concept description and image title/description (sentence-transformers)
- `clip_alignment`: CLIP alignment between concept text and image pixels
- Acceptance threshold: `≥ 0.50`

**State Transition Rules:**
- Concept description → query built for each source
- Raw results → licence filter removes non-open or unverifiable
- Filtered results → composite score computed
- Scored results → threshold filter (≥ 0.50)
- Accepted images → attribution captured and displayed
- All accepted images → stored in `note_assets` with mandatory `source_url` + `licence`

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create image retrieval Pydantic models | Import succeeds, mypy passes |
| 2 | Create source clients: Openverse, Wikimedia, NASA, USGS | T62.1: returns only openly-licensed |
| 3 | Create licence filter and verification service | T62.2: every image has source_url + licence |
| 4 | Create composite scorer (text-similarity + CLIP) | T62.3: precision@1 > 0.70 |
| 5 | Create threshold filter | T62.4: below threshold routes to generation |
| 6 | Create attribution formatter | T62.5: attribution visible in client |
| 7 | Verify no general web search exists | T62.6: code search confirms |
| 8 | Write integration tests | All T62.x tests pass |

**Atomic Sub-tasks:**
1. Image retrieval models and enums
2. Openverse API client
3. Wikimedia Commons API client
4. NASA/NIH/PMC/USGS API clients
5. Open Clipart client
6. Licence verification service
7. Composite scorer (text-similarity + CLIP alignment)
8. Threshold filter
9. Attribution formatter and display
10. Integration test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Source API rate-limited | Respect rate limit; queue and retry; log warning |
| Image URL returns 404 | Skip image; log warning |
| Licence cannot be determined | Reject image (UNVERIFIABLE); log warning |
| CLIP model OOM | Fall back to text-similarity-only scoring; log warning |
| All images below threshold | Return empty list; route concept to S63 (generation) |
| Source API returns non-JSON | Skip source; log warning; continue with other sources |
| Image format not decodable by CLIP | Skip image; log warning |
| Attribution field missing from source | Use "Unknown author"; log warning |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: Source client per image source (Openverse, Wikimedia, etc.)
- Pipeline pattern: query → fetch → licence_filter → score → threshold → store
- Adapter pattern: Each source API adapted to common `RetrievedImage` format
- Circuit breaker: Disable source after repeated failures

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`OpenverseClient`, `CompositeScorer`, `LicenceFilter`)
- Files: snake_case (`openverse.py`, `scorer.py`, `licence.py`)
- Functions: snake_case (`query_source`, `filter_by_licence`, `compute_score`)
- Constants: UPPER_SNAKE_CASE (`SCORE_THRESHOLD`, `MAX_RESULTS_PER_SOURCE`)

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- LicenceCategory enum enforced at schema level
- `source_url` and `licence` are non-nullable on `note_assets` (DB constraint from S10)

---

### 5. API & Interface Contracts

**Internal Service Interface (called by visual enrichment pipeline):**
```python
# src/services/image_retrieval/service.py
class ImageRetrievalService:
    async def retrieve_for_concept(
        self,
        concept_description: str,
        note_section_id: UUID,
        max_results: int = 5,
    ) -> ImageRetrievalResult:
        """Retrieve licensed images for a concept description."""
        ...

    async def get_attribution(self, image_id: UUID) -> AttributionDisplay:
        """Get formatted attribution for an image."""
        ...
```

**Source Client Interface:**
```python
# src/services/image_retrieval/sources/base.py
from abc import ABC, abstractmethod


class ImageSourceClient(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[RetrievedImage]:
        """Search source for images matching query."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if source API is reachable."""
        ...
```

**Mock Request/Response Payloads:**
```json
// Internal: ImageRetrievalService.retrieve_for_concept
// Input: concept_description="Anatomy of the human heart"
// Output:
{
  "concept_description": "Anatomy of the human heart",
  "images_retrieved": 25,
  "images_after_licence_filter": 18,
  "images_after_score_filter": 3,
  "accepted_images": [
    {
      "retrieved": {
        "id": "12345",
        "source": { "name": "wikimedia", "base_url": "https://commons.wikimedia.org" },
        "source_url": "https://commons.wikimedia.org/wiki/File:Human_heart_anatomy.svg",
        "image_url": "https://upload.wikimedia.org/.../Human_heart_anatomy.svg",
        "title": "Human Heart Anatomy",
        "licence": "cc-by-sa",
        "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "author": "OpenStax",
        "width": 800,
        "height": 600
      },
      "text_similarity": 0.82,
      "clip_alignment": 0.78,
      "composite_score": 0.80,
      "accepted": true
    }
  ],
  "source_breakdown": { "wikimedia": 12, "openverse": 8, "nasa": 5 },
  "best_match": { "..." }
}
```

**Attribution Display (client-side):**
```json
{
  "image_id": "...",
  "source_url": "https://commons.wikimedia.org/wiki/File:Human_heart_anatomy.svg",
  "licence": "cc-by-sa",
  "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
  "author": "OpenStax",
  "attribution_text": "Human Heart Anatomy by OpenStax, licensed under CC BY-SA 4.0"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `OPENVERSE_API_URL` | string | Openverse API base URL | `https://api.openverse.org/v1` |
| `OPENVERSE_RATE_LIMIT` | int | Requests per minute to Openverse | `60` |
| `WIKIMEDIA_API_URL` | string | Wikimedia Commons API URL | `https://commons.wikimedia.org/w/api.php` |
| `NASA_API_KEY` | string | NASA API key for imagery | `DEMO_KEY` |
| `USGS_API_URL` | string | USGS image service URL | `https://labs.gbif.org/` |
| `CLIP_MODEL_NAME` | string | CLIP model for alignment scoring | `openai/clip-vit-base-patch32` |
| `IMAGE_SCORE_THRESHOLD` | float | Minimum composite score for acceptance | `0.50` |
| `MAX_RESULTS_PER_SOURCE` | int | Max results per source per query | `10` |

**Third-Party Integration Contracts:**
- Openverse API: WordPress/Creative Commons image search
- Wikimedia Commons API: MediaWiki-based image search
- NASA Image API: NASA imagery and media
- USGS: Geological and topographical imagery
- CLIP: OpenAI CLIP model for image-text alignment
- sentence-transformers: Text similarity scoring

**Version Pins:**
- `openai-clip` or `open-clip-torch` pinned in `pyproject.toml`
- `sentence-transformers` pinned in `pyproject.toml`
- `httpx` pinned in `pyproject.toml`

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T62.1 | I | `pytest tests/test_image_retrieval.py::test_only_licensed -v` | Retrieval returns only openly-licensed results |
| T62.2 | I | `pytest tests/test_image_retrieval.py::test_source_url_licence_not_null -v` | Every used image has non-null source_url and licence |
| T62.3 | V | `pytest tests/test_image_scorer.py::test_precision_at_1 -v` | precision@1 > 0.70 on 200 labelled concept/image pairs |
| T62.4 | I | `pytest tests/test_image_retrieval.py::test_below_threshold_routes -v` | Score below threshold routes to generation |
| T62.5 | E | `pytest tests/test_image_retrieval.py::test_attribution_visible -v` | Attribution and licence visible in client alongside every web image |
| T62.6 | I | `pytest tests/test_image_retrieval.py::test_no_web_search -v` | No general web image search endpoint exists in codebase |

**Test Case Details (Given/When/Then):**

**T62.1 — Retrieval returns only openly-licensed results**
- **Given:** concept description "Nebula formation in deep space"
- **When:** image retrieval queries Openverse, Wikimedia, and NASA
- **Then:** all returned images have a verified open licence; no CC-BY-NC-ND or proprietary licences present; licence category in response

**T62.2 — Every image has source_url and licence**
- **Given:** 10 images retrieved and accepted for various concepts
- **When:** images are stored in `note_assets`
- **Then:** every record has non-null `source_url` and `licence`; DB constraint `note_assets_source_url_not_null` passes; no image stored without attribution data

**T62.3 — precision@1 > 0.70**
- **Given:** 200 concept/image pairs with human-labelled relevance
- **When:** composite scorer ranks images for each concept
- **Then:** precision@1 (top result is relevant) > 0.70; results logged with per-query scores

**T62.4 — Below threshold routes to generation**
- **Given:** concept description "Microscopic structure of a neuron" with no good matches (best score = 0.35)
- **When:** threshold filter applies (≥ 0.50)
- **Then:** no images accepted; concept routed to S63 (AI generation); event emitted

**T62.5 — Attribution visible in client**
- **Given:** an accepted image with licence=CC-BY-SA, author="OpenStax"
- **When:** image is rendered in the client note view
- **Then:** attribution text displayed: "Human Heart Anatomy by OpenStax, licensed under CC BY-SA 4.0"; source_url is a clickable link

**T62.6 — No general web image search endpoint exists**
- **Given:** the entire codebase
- **When:** code search for web image search API patterns (e.g., Google Images API, Bing Image Search, SerpAPI)
- **Then:** no matches found; no endpoint or client for general web image search exists

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Openverse API may return CC-BY-NC images — licence filter must reject these
- Wikimedia API has strict rate limits — respect `Retry-After` headers
- CLIP model requires GPU — enforce VRAM budget from S02
- NASA API key `DEMO_KEY` has low rate limits — use production key in production
- Some sources return images without licence metadata — reject as UNVERIFIABLE
- Composite scoring formula weights (0.5/0.5) may need tuning — log per-component scores for analysis
- Image URL may be a redirect — follow redirects but verify final URL is accessible

**Fallback Instructions:**
- If Openverse unavailable: skip; continue with other sources; log warning
- If Wikimedia rate-limited: queue and retry; log warning
- If CLIP OOM: fall back to text-similarity-only scoring; log warning
- If all sources fail: return empty results; route concept to S63
- If image download fails: skip image; log warning

**Rollback Procedure:**
- Disable image retrieval: feature flag `IMAGE_RETRIEVAL_ENABLED=false`
- Image assets are additive — removing them doesn't break notes
- Database migration is additive (new columns on `note_assets`)
- Source clients can be disabled individually via env vars

---

### 9. Observability (if applicable)

**Metrics Added:**
- `image_retrieval_queries_total`: counter of retrieval queries
- `image_retrieval_results_total`: counter of results per source (labels: source)
- `image_retrieval_licence_filtered_total`: counter of images removed by licence filter
- `image_retrieval_score_distribution`: histogram of composite scores
- `image_retrieval_accepted_total`: counter of accepted images
- `image_retrieval_precision_at_1`: gauge of precision@1 (updated per test run)
- `image_retrieval_source_latency_seconds`: histogram per source (labels: source)
- `image_retrieval_clips_scoring_seconds`: histogram of CLIP scoring time

**Tracing/Logging:**
- Span: `image_retrieval.query` with child spans per source
- Span: `image_retrieval.score` with attributes (text_sim, clip_align, composite)
- Log: INFO on retrieval with source, count, accepted count
- Log: WARN on licence rejection with image ID and licence
- Log: INFO on threshold routing with score and target service
- Log: ERROR on source failure with error details

**Alerts:**
- precision@1 drops below 0.60: investigate scorer or source quality
- Licence filter rejection rate > 30%: investigate source licence metadata
- CLIP scoring latency > 5s per image: investigate GPU availability

---

### 10. Exit Checklist

- [ ] All tests pass (T62.1–T62.6)
- [ ] Only openly-licensed images returned (T62.1)
- [ ] Every used image has non-null source_url and licence (T62.2)
- [ ] precision@1 > 0.70 on labelled pairs (T62.3)
- [ ] Below-threshold concepts route to generation (T62.4)
- [ ] Attribution visible in client (T62.5)
- [ ] No general web image search endpoint exists (T62.6)
- [ ] Composite scorer implemented with §9.4 formula
- [ ] All source clients implemented (Openverse, Wikimedia, NASA, USGS, Open Clipart)
