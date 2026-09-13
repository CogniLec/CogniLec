# S61 — Concept Detection & Text-Diagram-First Path
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Detect transcript concepts warranting a visual (board references, spatial/structural descriptions, named diagrams, processes), then attempt text-representable diagrams first — Mermaid for flows/trees/state machines, Graphviz/D2 for graphs, Excalidraw-style for hand-drawn aesthetic, KaTeX for formulas — and route only genuinely pictorial concepts (anatomy, apparatus, geography) to image retrieval or generation. This validates D-25's premise that text diagrams resolve a significant proportion of visual needs.

**Component Boundaries:**
- **Allowed:** `src/services/visual_enrichment/`, `src/services/visual_enrichment/concept_detector.py`, `src/services/visual_enrichment/text_diagrams/`, `src/services/visual_enrichment/text_diagrams/mermaid.py`, `src/services/visual_enrichment/text_diagrams/graphviz.py`, `src/services/visual_enrichment/text_diagrams/katex.py`, `src/services/visual_enrichment/text_diagrams/excalidraw.py`, `src/services/visual_enrichment/router.py`, `tests/test_concept_detection.py`, `tests/test_text_diagrams.py`
- **Off-limits:** Image retrieval (S62), image generation (S63), visual assembly (S64), note synthesis agent (S44)

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Mermaid CLI | 10.x | Mermaid diagram rendering/validation |
| Graphviz | 12.x | Graph/dot diagram generation |
| D2 | 0.6.x | Alternative graph diagram language |
| KaTeX | 0.16.x | LaTeX math rendering |
| Pydantic | 2.13.5 | Concept and diagram schemas |
| pytest | 8.x | Integration tests |

---

### 2. State Machine & Domain Schemas

**Visual Need Detection Flow:**
```
note_section → concept_detection → concept_list
    → for each concept:
        → classify concept type
        → if text_representable: generate diagram → validate → attach
        → if genuinely_pictorial: route to S62/S63
```

**Concept Type Classification:**
```python
# src/services/visual_enrichment/models.py
from enum import Enum


class ConceptType(str, Enum):
    FLOWCHART = "flowchart"  # Mermaid
    TREE_HIERARCHY = "tree"  # Mermaid
    STATE_MACHINE = "state_machine"  # Mermaid
    SEQUENCE_DIAGRAM = "sequence"  # Mermaid
    GRAPH_NETWORK = "graph"  # Graphviz/D2
    MATH_FORMULA = "formula"  # KaTeX
    TABLE = "table"  # Markdown table
    TIMELINE = "timeline"  # Mermaid
    CLASS_DIAGRAM = "class_diagram"  # Mermaid
    GENUINELY_PICTORIAL = "pictorial"  # S62/S63 (anatomy, geography, apparatus)
    UNKNOWN = "unknown"  # Skip visual


class DiagramFormat(str, Enum):
    MERMAID = "mermaid"
    GRAPHVIZ = "graphviz"
    D2 = "d2"
    KATEX = "katex"
    MARKDOWN_TABLE = "markdown_table"
    EXCALIDRAW = "excalidraw"


class VisualRoute(str, Enum):
    TEXT_DIAGRAM = "text_diagram"  # Resolved by Mermaid/KaTeX/etc.
    LICENSED_IMAGE = "licensed_image"  # Route to S62
    AI_GENERATED = "ai_generated"  # Route to S63
    SKIPPED = "skipped"  # No visual needed
```

**Pydantic Schemas:**
```python
# src/services/visual_enrichment/models.py
from pydantic import BaseModel, Field
from uuid import UUID


class DetectedConcept(BaseModel):
    id: UUID
    note_section_id: UUID
    concept_type: ConceptType
    description: str = Field(..., max_length=2000)
    source_text: str = Field(..., max_length=5000)
    confidence: float = Field(..., ge=0.0, le=1.0)
    route: VisualRoute
    diagram_format: DiagramFormat | None = None


class TextDiagram(BaseModel):
    id: UUID
    concept_id: UUID
    format: DiagramFormat
    syntax: str = Field(..., max_length=10000)
    is_valid: bool = False
    validation_errors: list[str] = Field(default_factory=list)
    render_path: str | None = None  # path to rendered SVG/PNG


class ConceptDetectionResult(BaseModel):
    note_section_id: UUID
    concepts_detected: list[DetectedConcept]
    text_diagrams_generated: list[TextDiagram]
    concepts_routed_to_image: list[DetectedConcept]
    total_concepts: int
    text_resolved_count: int
    image_routed_count: int
    text_resolution_ratio: float  # text_resolved / total (validates D-25)


class DiagramValidationResult(BaseModel):
    format: DiagramFormat
    syntax: str
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

**Concept Detection Rules (SRS FR-4.1, D-25):**
```
Board references → ConceptType.FLOWCHART or TREE_HIERARCHY
Spatial/structural descriptions → ConceptType.GRAPH_NETWORK
Named diagrams ("as shown in the diagram") → ConceptType.UNKNOWN (needs context)
Processes/steps → ConceptType.FLOWCHART
State transitions → ConceptType.STATE_MACHINE
Mathematical expressions → ConceptType.MATH_FORMULA
Hierarchies/taxonomies → ConceptType.TREE_HIERARCHY
Anatomy/geography/apparatus → ConceptType.GENUINELY_PICTORIAL
```

**State Transition Rules:**
- Concept detected → classified by type
- Text-representable concept → diagram generated in appropriate format
- Diagram validated (syntax check) → attached to note section
- Genuinely pictorial concept → routed to S62 (licensed image retrieval)
- Invalid diagram → logged as warning; concept still marked as text-resolved with fallback

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Create visual enrichment Pydantic models | Import succeeds, mypy passes |
| 2 | Create `src/services/visual_enrichment/concept_detector.py` | T61.1: precision > 0.75 |
| 3 | Create `src/services/visual_enrichment/text_diagrams/mermaid.py` | T61.2: flowchart → valid Mermaid |
| 4 | Create `src/services/visual_enrichment/text_diagrams/graphviz.py` | T61.3: hierarchy → valid tree |
| 5 | Create `src/services/visual_enrichment/text_diagrams/katex.py` | KaTeX formulas render |
| 6 | Create diagram validation service | T61.6: all syntax renders without error |
| 7 | Create `src/services/visual_enrichment/router.py` | T61.5: pictorial concepts route correctly |
| 8 | Measure text diagram resolution ratio | T61.4: ratio measured |
| 9 | Write integration tests | All T61.x tests pass |

**Atomic Sub-tasks:**
1. Concept detection models and enums
2. Concept detector (LLM-based classification)
3. Mermaid diagram generator
4. Graphviz/D2 diagram generator
5. KaTeX formula generator
6. Diagram validation service (syntax checking)
7. Visual routing logic (text diagram vs image path)
8. Text diagram resolution ratio measurement
9. Integration test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Mermaid syntax invalid | Log warning; mark diagram invalid; concept still counts as text-resolved |
| Graphviz not installed | Fall back to D2 for graph types; log warning |
| KaTeX formula unparseable | Include raw LaTeX; log warning |
| Concept type ambiguous | Default to `UNKNOWN`; skip visual |
| No concepts detected in section | Normal; not all sections need visuals |
| Genuinely pictorial concept with no good retrieval result | Route to S63 (AI generation) |
| Diagram syntax exceeds max length | Truncate; log warning |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Strategy pattern: Diagram generator per format (Mermaid, Graphviz, KaTeX)
- Pipeline pattern: detect → classify → generate → validate → route
- Factory pattern: DiagramGeneratorFactory for format selection
- Chain of responsibility: concept type → format selection

**Naming & Style Guidelines:**
- Variables: snake_case
- Classes: PascalCase (`ConceptDetector`, `MermaidGenerator`, `DiagramValidator`)
- Files: snake_case (`concept_detector.py`, `mermaid.py`, `diagram_validator.py`)
- Functions: snake_case (`detect_concepts`, `generate_mermaid`, `validate_syntax`)
- Constants: UPPER_SNAKE_CASE

**Code Splitting Metrics:**
- Max function length: 40 lines
- Max file length: 300 lines
- Max class methods: 8

**Type Safety:**
- All function signatures typed with Pydantic v2 models
- `from __future__ import annotations` in all files
- ConceptType and DiagramFormat enums enforced at schema level

---

### 5. API & Interface Contracts

**Internal Service Interface (not exposed via API — called by note pipeline):**
```python
# src/services/visual_enrichment/service.py
class VisualEnrichmentService:
    async def detect_and_resolve(
        self, note_section_id: UUID, section_text: str
    ) -> ConceptDetectionResult:
        """Detect visual concepts in a note section and resolve where possible."""
        ...

    async def generate_text_diagram(self, concept: DetectedConcept) -> TextDiagram:
        """Generate a text diagram for a detected concept."""
        ...

    async def validate_diagram(self, diagram: TextDiagram) -> DiagramValidationResult:
        """Validate diagram syntax."""
        ...
```

**Diagram Generator Interface:**
```python
# src/services/visual_enrichment/text_diagrams/base.py
from abc import ABC, abstractmethod


class DiagramGenerator(ABC):
    @abstractmethod
    async def generate(self, concept: DetectedConcept) -> TextDiagram:
        """Generate diagram syntax from concept description."""
        ...

    @abstractmethod
    async def validate(self, syntax: str) -> DiagramValidationResult:
        """Validate diagram syntax."""
        ...

    @abstractmethod
    async def render(self, syntax: str, output_path: str) -> str:
        """Render diagram to SVG/PNG. Returns output path."""
        ...
```

**Event/Message Contracts:**
```json
// Event: visual_enrichment.concept_detected
{
  "event_type": "visual_enrichment.concept_detected",
  "note_section_id": "...",
  "concept_type": "flowchart",
  "route": "text_diagram",
  "confidence": 0.85
}

// Event: visual_enrichment.routed_to_image
{
  "event_type": "visual_enrichment.routed_to_image",
  "note_section_id": "...",
  "concept_type": "pictorial",
  "route": "licensed_image",
  "description": "Anatomy of the human heart"
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Default |
|----------|------|-------------|---------|
| `CONCEPT_DETECTION_MODEL` | string | LLM model for concept detection | `gpt-4o-mini` |
| `CONCEPT_DETECTION_THRESHOLD` | float | Min confidence for concept detection | `0.70` |
| `GRAPHVIZ_PATH` | string | Path to graphviz binary | `dot` |
| `D2_PATH` | string | Path to D2 binary | `d2` |
| `MERMAID_CLI_PATH` | string | Path to mermaid CLI | `mmdc` |
| `KATEX_CDN_URL` | string | KaTeX CDN for client rendering | `https://cdn.jsdelivr.net/npm/katex@0.16/` |
| `DIAGRAM_MAX_SYNTAX_LENGTH` | int | Max diagram syntax characters | `10000` |

**Third-Party Integration Contracts:**
- Mermaid CLI: Diagram rendering and syntax validation
- Graphviz: Graph/network diagram generation
- D2: Alternative graph diagram language
- KaTeX: LaTeX math rendering (client-side via CDN)

**Version Pins:**
- `@mermaid-js/mermaid-cli` pinned in `package.json` (Node side)
- `graphviz` system package pinned in Dockerfile
- `d2` pinned in Dockerfile

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T61.1 | V | `pytest tests/test_concept_detection.py::test_precision -v` | Concept detection precision > 0.75 on labelled transcripts |
| T61.2 | I | `pytest tests/test_text_diagrams.py::test_flowchart_mermaid -v` | Described flowchart produces valid Mermaid |
| T61.3 | I | `pytest tests/test_text_diagrams.py::test_hierarchy_tree -v` | Described hierarchy produces valid tree diagram |
| T61.4 | V | `pytest tests/test_text_diagrams.py::test_resolution_ratio -v` | Proportion of concepts resolved by text diagrams measured |
| T61.5 | I | `pytest tests/test_text_diagrams.py::test_pictorial_routing -v` | Genuinely pictorial concept correctly routes to image path |
| T61.6 | I | `pytest tests/test_text_diagrams.py::test_all_render -v` | All generated diagram syntax renders without error client-side |

**Test Case Details (Given/When/Then):**

**T61.1 — Concept detection precision > 0.75**
- **Given:** 100 note sections with manually labelled visual needs (50 positive, 50 negative)
- **When:** concept detector processes each section
- **Then:** precision > 0.75 (at least 75% of detected concepts are true positives); recall also measured and logged

**T61.2 — Flowchart produces valid Mermaid**
- **Given:** a note section describing: "The process goes: data collection → preprocessing → model training → evaluation → deployment"
- **When:** concept detector identifies this as a flowchart and Mermaid generator runs
- **Then:** output is syntactically valid Mermaid (`graph TD` with nodes and edges); `mermaid-cli` renders without error

**T61.3 — Hierarchy produces valid tree diagram**
- **Given:** a note section describing: "The classification hierarchy is: Animal → Mammal → Primate → Human"
- **When:** concept detector identifies this as a tree hierarchy and Mermaid generator runs
- **Then:** output is syntactically valid Mermaid tree; renders without error

**T61.4 — Text diagram resolution ratio measured**
- **Given:** 200 note sections with detected concepts
- **When:** visual enrichment pipeline runs on all sections
- **Then:** `ConceptDetectionResult.text_resolution_ratio` computed; ratio logged as a metric; validates D-25's premise that text diagrams resolve a significant proportion of visual needs

**T61.5 — Pictorial concept routes to image path**
- **Given:** a note section describing: "The anatomy of the human heart includes the left ventricle, right atrium, and aorta"
- **When:** concept detector identifies this as genuinely pictorial
- **Then:** `route=licensed_image`; concept is NOT resolved by text diagram; concept passed to S62 pipeline

**T61.6 — All generated diagrams render without error**
- **Given:** 20 concepts of various types (flowchart, tree, state machine, formula, graph)
- **When:** text diagram generators produce syntax for each
- **Then:** all 20 diagrams pass syntax validation; all render to SVG/PNG without error

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Mermaid CLI requires Node.js — ensure it's in the Docker image
- Graphviz `dot` binary must be installed at system level
- KaTeX rendering is client-side — validate syntax server-side, render client-side
- Concept detection precision depends heavily on prompt quality — iterate on prompt
- Some concepts are genuinely ambiguous between text diagram and pictorial — default to text diagram when possible (D-25 preference)
- Diagram syntax length limits may truncate complex diagrams — split into multiple diagrams

**Fallback Instructions:**
- If Mermaid CLI unavailable: store raw syntax; client renders if available; log warning
- If Graphviz unavailable: fall back to D2 for graph types; log warning
- If KaTeX CDN unreachable: store raw LaTeX; client renders when CDN available
- If concept detection fails: skip visual enrichment for that section; log warning
- If diagram validation fails: store raw syntax; mark as invalid; still count as text-resolved

**Rollback Procedure:**
- Disable text diagrams: feature flag `TEXT_DIAGRAMS_ENABLED=false`
- Disable concept detection: feature flag `CONCEPT_DETECTION_ENABLED=false`
- Text diagrams are additive — removing them doesn't break notes
- No database migrations required for this stage

---

### 9. Observability (if applicable)

**Metrics Added:**
- `concept_detection_total`: counter of concepts detected (labels: concept_type, route)
- `concept_detection_precision`: gauge of detection precision (updated per test run)
- `text_diagrams_generated_total`: counter of text diagrams generated (labels: format)
- `text_diagram_resolution_ratio`: gauge of D-25 resolution ratio
- `text_diagram_validation_success_rate`: gauge of syntax validation pass rate
- `text_diagram_render_latency_seconds`: histogram of diagram rendering time
- `concepts_routed_to_image_total`: counter of concepts routed to S62/S63

**Tracing/Logging:**
- Span: `visual_enrichment.detect` with child spans for each concept
- Span: `visual_enrichment.generate_diagram` with attributes (format, concept_type)
- Span: `visual_enrichment.validate_diagram` with attributes (is_valid, errors)
- Log: INFO on concept detection with concept_type and route
- Log: INFO on diagram generation with format and validity
- Log: WARN on diagram validation failure with errors
- Log: INFO on routing decision with concept_type and target service

**Alerts:**
- Concept detection precision drops below 0.70: investigate prompt or model
- Diagram validation failure rate > 10%: investigate generator quality
- Text diagram resolution ratio < 0.30: investigate concept detection or generator

---

### 10. Exit Checklist

- [ ] All tests pass (T61.1–T61.6)
- [ ] Concept detection precision > 0.75 on labelled transcripts (T61.1)
- [ ] Flowchart produces valid Mermaid (T61.2)
- [ ] Hierarchy produces valid tree diagram (T61.3)
- [ ] Text diagram resolution ratio measured (T61.4)
- [ ] Genuinely pictorial concepts route to image path (T61.5)
- [ ] All generated diagrams render without error (T61.6)
- [ ] Text-representable diagrams produced deterministically
- [ ] D-25 premise validated with measured resolution ratio
