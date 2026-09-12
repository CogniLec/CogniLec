# S73 — Performance Tuning to NFR Targets
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Measure and tune the system against every NFR-P performance target (NFR-P1 through NFR-P7), including HNSW parameter tuning per partition, PgBouncer pool sizing, Prefect concurrency limits, Locust load testing at 20 concurrent sessions, and VectorChord evaluation for re-embed insert throughput (D-27).

**Component Boundaries:**
- **Allowed:** `tests/performance/`, `config/pgbouncer/`, `config/prefect/`, `config/hnsw/`, `scripts/benchmark/`, `docs/performance/`
- **Off-limits:** Application source code changes (tuning only, not refactoring), database schema changes, model training code

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Locust | 2.x | Load testing framework |
| HypoPG | 2.1.x | Hypothetical index tuning |
| pg_qualstats | 0.2.x | Query qualification statistics |
| PgBouncer | 1.23.x | Connection pooling |
| pgvector | 0.8.x | HNSW vector search |
| VectorChord | 0.2.x | Alternative vector index (D-27 evaluation) |
| Prometheus | 2.53.x | Metrics collection during tests |
| Grafana | 11.x | Performance dashboards |

---

### 2. State Machine & Domain Schemas

**NFR-P Targets:**
```
NFR-P1: ASR real-time factor < 1.0
NFR-P2: Topic window result <= 60s after the 10-minute mark
NFR-P3: Post-session processing <= 15 min P90 for a 60-minute lecture
NFR-P4: Consolidated note retrieval < 3s P95
NFR-P5: 20-question test < 30s P90
NFR-P6: Vector search < 200ms P95
NFR-P7: >= 20 concurrent live sessions sustained on one node
```

**Performance Test Suite Structure:**
```python
# tests/performance/test_nfr_targets.py
class NFRPerformanceSuite:
    """Locust-based performance test suite for NFR-P targets."""
    targets = {
        "NFR_P1": {"metric": "asr_real_time_factor", "threshold": 1.0, "percentile": "mean"},
        "NFR_P2": {"metric": "topic_window_latency_s", "threshold": 60, "percentile": "p100"},
        "NFR_P3": {"metric": "post_session_processing_s", "threshold": 900, "percentile": "p90"},
        "NFR_P4": {"metric": "note_retrieval_s", "threshold": 3.0, "percentile": "p95"},
        "NFR_P5": {"metric": "test_generation_s", "threshold": 30, "percentile": "p90"},
        "NFR_P6": {"metric": "vector_query_s", "threshold": 0.2, "percentile": "p95"},
        "NFR_P7": {"metric": "concurrent_sessions", "threshold": 20, "percentile": "sustained"},
    }
```

**HNSW Parameter Search Space:**
```python
# config/hnsw/param_search.yaml
hnsw_param_search:
  pg_main:
    m_range: [16, 32, 64]
    ef_construction_range: [100, 200, 400]
    ef_search_range: [50, 100, 200]
  partitions:
    - name: "embeddings_utterances"
      m: 32
      ef_construction: 200
      ef_search: 100
    - name: "embeddings_notes"
      m: 16
      ef_construction: 100
      ef_search: 50
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Set up Locust load test framework with LIS-specific users | `locust -f tests/performance/locustfile.py` starts |
| 2 | Create baseline performance measurements for all NFR-P targets | Baseline report generated |
| 3 | Tune PgBouncer pool size (test 10, 20, 50, 100 connections) | Optimal pool size identified |
| 4 | Tune Prefect concurrency limits (test 5, 10, 20 workers) | Optimal concurrency identified |
| 5 | Run HypoPG/pg_qualstats analysis on hot queries | Index recommendations generated |
| 6 | Tune HNSW parameters per partition using search space | Optimal parameters identified |
| 7 | Re-run performance tests with tuned parameters | All NFR-P targets met |
| 8 | Run 20-concurrent-session load test (NFR-P7) | Sustained throughput verified |
| 9 | Evaluate VectorChord vs pgvector for re-embed insert throughput | D-27 decision documented |
| 10 | Generate performance report vs all targets | Report complete |
| 11 | Create repeatable CI performance test suite | Suite runs in CI pipeline |
| 12 | Run all T73.x tests | All pass |

**Atomic Sub-tasks:**
1. Locust load test framework setup
2. Baseline measurement for all NFR-P targets
3. PgBouncer connection pool tuning
4. Prefect concurrency tuning
5. HNSW parameter tuning per partition
6. VectorChord evaluation (D-27)
7. Performance report generation
8. CI-integrated performance test suite

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| ASR real-time factor exceeds 1.0 | Check GPU utilisation; increase batch size or use faster model |
| Vector search exceeds 200ms P95 | Tune HNSW ef_search; check index size; consider partition splitting |
| 20 concurrent sessions fail | Check PgBouncer pool; increase Prefect workers; check GPU memory |
| Post-session processing exceeds 15 min | Profile pipeline; identify bottleneck agent; tune LLM tier |
| Locust test crashes | Reduce concurrent users; check resource limits |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Benchmark harness pattern (Locust users simulating real workflows)
- Statistical analysis (percentile-based thresholding)
- A/B comparison (pgvector vs VectorChord)

**Naming & Style Guidelines:**
- Test files: `tests/performance/test_nfr_*.py`
- Benchmark scripts: `scripts/benchmark/`
- Performance reports: `docs/performance/`
- Config tuning: `config/pgbouncer/`, `config/hnsw/`

**Code Splitting Metrics:**
- Max test file length: 500 lines
- Max benchmark script: 200 lines
- Performance report: max 30 pages

**Type Safety:**
- All performance assertions use typed thresholds
- Locust users use typed request/response models
- Benchmark results stored as typed dataclasses

---

### 5. API & Interface Contracts

**Locust Load Test Scenarios:**
```python
# tests/performance/locustfile.py
from locust import HttpUser, task, between

class LISStudentUser(HttpUser):
    """Simulates a student using the LIS system."""
    wait_time = between(1, 5)

    @task(10)
    def record_session(self):
        """Simulate recording a lecture session."""
        self.client.post("/api/v1/sessions", json={"subject_id": "...", "session_type": "content"})

    @task(5)
    def get_notes(self):
        """Retrieve consolidated notes."""
        self.client.get(f"/api/v1/sessions/{self.session_id}/notes")

    @task(3)
    def vector_search(self):
        """Search across embeddings."""
        self.client.post("/api/v1/search", json={"query": "neural networks", "subject_id": "..."})

    @task(2)
    def generate_test(self):
        """Generate a practice test."""
        self.client.post(f"/api/v1/sessions/{self.session_id}/test", json={"num_questions": 20})
```

**Performance Benchmark Results Schema:**
```python
@dataclass
class NFRBenchmarkResult:
    nfr_id: str  # NFR-P1, NFR-P2, etc.
    metric_name: str
    threshold: float
    measured_value: float
    percentile: str  # mean, p50, p90, p95, p99
    passed: bool
    measurement_window_s: int
    sample_size: int
    timestamp: datetime
    notes: str | None = None
```

**VectorChord Comparison Schema:**
```python
@dataclass
class VectorIndexBenchmark:
    index_type: str  # hnsw (pgvector), vamana (VectorChord)
    insert_throughput_rows_per_s: float
    query_latency_p95_ms: float
    index_size_mb: float
    build_time_s: float
    memory_usage_mb: float
    recommendation: str  # "pgvector", "vectorchord", "hybrid"
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `DATABASE_URL` | string | PG-MAIN connection | `postgresql+asyncpg://localhost:5432/lis` |
| `PGBOUNCER_POOL_SIZE` | int | PgBouncer pool size | `20` |
| `PREFECT_CONCURRENCY_LIMIT` | int | Prefect worker concurrency | `10` |
| `LOCUST_USERS` | int | Number of concurrent Locust users | `20` |
| `LOCUST_SPAWN_RATE` | int | User spawn rate | `2` |
| `LOCUST_RUN_TIME` | string | Test duration | `10m` |
| `HNSW_M` | int | HNSW M parameter | `32` |
| `HNSW_EF_CONSTRUCTION` | int | HNSW ef_construction | `200` |
| `HNSW_EF_SEARCH` | int | HNSW ef_search | `100` |
| `VECTORCHORD_EVAL_ENABLED` | bool | Enable VectorChord eval | `true` |

**Performance Test Data Requirements:**
- 100 sessions with transcripts (minimum)
- 10,000 utterances with embeddings
- 1,000 note sections
- 50 subjects with diverse content
- 20 concurrent user sessions for NFR-P7

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T73.1 | P | ASR pipeline configured with production model | Process 60-minute lecture | Real-time factor < 1.0 (NFR-P1) |
| T73.2 | P | 10-minute session recorded with 2+ topics | Topic window algorithm runs | Result available <= 60s after 10-minute mark (NFR-P2) |
| T73.3 | P | 60-minute lecture with full pipeline | Post-session processing runs | Processing completes <= 15 min P90 (NFR-P3) |
| T73.4 | P | Notes consolidated for a subject with 10+ sessions | Note retrieval query executes | Response < 3s P95 (NFR-P4) |
| T73.5 | P | Session with notes available | 20-question test generation requested | Generation completes < 30s P90 (NFR-P5) |
| T73.6 | P | 31k+ vectors in a partition | Vector search query executes | Query returns in < 200ms P95 (NFR-P6) |
| T73.7 | P | System configured for production load | 20 concurrent live sessions sustained for 30 minutes | All sessions complete without degradation; throughput sustained (NFR-P7) |
| T73.8 | P | Full-subject re-embed dataset (10k rows) | VectorChord insert benchmark vs pgvector | Throughput comparison documented; D-27 decision recorded |

**Verification Commands:**
```bash
# Run all performance tests
uv run locust -f tests/performance/locustfile.py --headless \
  -u $LOCUST_USERS -r $LOCUST_SPAWN_RATE --run-time $LOCUST_RUN_TIME \
  --csv=results/performance

# Run individual NFR tests
uv run pytest tests/performance/test_nfr_targets.py -v -k "NFR_P1"
uv run pytest tests/performance/test_nfr_targets.py -v -k "NFR_P7"

# Run VectorChord evaluation
uv run pytest tests/performance/test_vectorchord.py -v

# Generate performance report
uv run python scripts/benchmark/generate_report.py --output docs/performance/report.md

# Full verification
uv run pytest tests/performance/ -v --tb=short && \
uv run python scripts/benchmark/generate_report.py
```

**Exit Criteria:**
- [ ] NFR-P1: ASR real-time factor < 1.0 (T73.1)
- [ ] NFR-P2: Topic window result <= 60s after 10-minute mark (T73.2)
- [ ] NFR-P3: Post-session processing <= 15 min P90 (T73.3)
- [ ] NFR-P4: Consolidated note retrieval < 3s P95 (T73.4)
- [ ] NFR-P5: 20-question test < 30s P90 (T73.5)
- [ ] NFR-P6: Vector search < 200ms P95 (T73.6)
- [ ] NFR-P7: >= 20 concurrent live sessions sustained (T73.7)
- [ ] VectorChord vs pgvector evaluated; D-27 decision recorded (T73.8)
- [ ] Performance report complete with all targets
- [ ] Repeatable CI performance test suite

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Locust tests may not reflect real-world patterns; use realistic user behaviour
- HNSW tuning is partition-specific; one-size-fits-all does not work
- PgBouncer pool too small causes connection starvation; too large wastes resources
- Prefect concurrency too high can cause GPU memory pressure
- VectorChord may not be production-ready; evaluate critically
- Performance results vary by hardware; document the test environment

**Fallback Instructions:**
- If NFR-P1 fails, check GPU utilisation and ASR batch size
- If NFR-P6 fails, increase HNSW ef_search or split partitions
- If NFR-P7 fails, increase PgBouncer pool and Prefect workers
- If VectorChord underperforms, stay with pgvector

**Rollback Procedure:**
- PgBouncer: revert `pgbouncer.ini` to previous pool size
- HNSW: revert index parameters via `ALTER INDEX ... SET (m=..., ef_construction=...)`
- Prefect: revert concurrency limits in Prefect server config
- No code changes; purely configuration rollback

---

### 9. Observability (if applicable)

**Metrics Added:**
- `lis_perf_nfr_p1_real_time_factor`: Gauge of ASR real-time factor
- `lis_perf_nfr_p2_topic_window_latency_s`: Gauge of topic window latency
- `lis_perf_nfr_p3_post_session_s`: Gauge of post-session processing time
- `lis_perf_nfr_p4_note_retrieval_s`: Gauge of note retrieval time
- `lis_perf_nfr_p5_test_generation_s`: Gauge of test generation time
- `lis_perf_nfr_p6_vector_query_s`: Gauge of vector query time
- `lis_perf_nfr_p7_concurrent_sessions`: Gauge of concurrent sessions
- `lis_perf_vectorchord_insert_throughput`: Gauge of VectorChord insert rate

**Tracing/Logging:**
- Span: `perf.nfr_p1_asr_benchmark` for ASR benchmark
- Span: `perf.nfr_p7_load_test` for concurrent session load test
- Log event: `perf_benchmark_complete` with nfr_id, result, threshold
- Log event: `perf_vectorchord_eval` with comparison results

**Alerts:**
- Alert if any NFR-P target regresses by > 10% from baseline
- Alert if performance test suite fails in CI

---

### 10. Exit Checklist

- [ ] All tests pass (T73.1 through T73.8)
- [ ] Every NFR-P target met and recorded
- [ ] HNSW parameters tuned per partition
- [ ] PgBouncer pool sized optimally
- [ ] Prefect concurrency limits set
- [ ] VectorChord evaluated; D-27 decision documented
- [ ] Performance report complete
- [ ] Repeatable CI performance test suite
- [ ] Test environment documented
