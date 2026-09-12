# S70 — Observability Stack
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy a consolidated observability stack (SigNoz or Prometheus + Grafana + Loki + Tempo) with exporters and seven production dashboards covering sessions funnel, WER proxy, cost, agent efficiency, topic health, GPU utilisation, and vector query latency — with alert rules routing through Alertmanager to n8n.

**Component Boundaries:**
- **Allowed:** `docker/compose/observability/`, `config/grafana/`, `config/prometheus/`, `config/alertmanager/`, `config/signoz/`, `deploy/observability/`, `tests/`
- **Off-limits:** Application source code (no changes to `src/`), database schemas, agent logic, model serving code

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| SigNoz | 0.60.x | Unified observability (metrics, traces, logs) OR |
| Prometheus | 2.53.x | Metrics collection (alternative stack) |
| Grafana | 11.x | Dashboard visualisation |
| Loki | 3.x | Log aggregation |
| Tempo | 2.x | Distributed tracing |
| Alertmanager | 0.27.x | Alert routing to n8n |
| dcgm-exporter | 3.3.x | GPU metrics (NVIDIA DCGM) |
| postgres-exporter | 0.15.x | PostgreSQL metrics |
| node-exporter | 1.8.x | Host-level metrics |
| cAdvisor | 0.49.x | Container metrics |
| GlitchTip | 3.x | Error tracking |
| Uptime Kuma | 1.x | Synthetic uptime monitoring |
| Docker Compose | 2.x | Deployment |

---

### 2. State Machine & Domain Schemas

**Alert Severity Levels:**
```
info → warning → critical → (auto-resolve when condition clears)
```

**Dashboard Registry Schema:**
```python
# Internal config — no DB table, managed via Grafana provisioning JSON
DASHBOARD_REGISTRY = {
    "sessions_funnel": {
        "uid": "lis-sessions-funnel",
        "title": "Sessions Funnel",
        "panels": ["sessions_created", "sessions_recording", "sessions_transcribed",
                    "sessions_processing", "sessions_complete", "sessions_failed"],
        "refresh": "30s",
    },
    "wer_proxy": {
        "uid": "lis-wer-proxy",
        "title": "WER Proxy (Mean ASR Confidence Trend)",
        "panels": ["asr_confidence_mean", "asr_confidence_p5", "asr_confidence_trend"],
        "refresh": "60s",
    },
    "cost_per_session": {
        "uid": "lis-cost-per-session",
        "title": "Cost per Session by Agent",
        "panels": ["cost_by_agent", "cost_total_daily", "token_usage_by_agent"],
        "refresh": "120s",
    },
    "a1_efficiency": {
        "uid": "lis-a1-efficiency",
        "title": "A1 Filter Efficiency",
        "panels": ["a1_discard_rate", "a1_precision", "a1_latency_p95"],
        "refresh": "60s",
    },
    "topic_health": {
        "uid": "lis-topic-health",
        "title": "Topic Health per Subject",
        "panels": ["topic_count_by_subject", "topic_stability", "merge_rate", "split_rate"],
        "refresh": "300s",
    },
    "gpu_utilisation": {
        "uid": "lis-gpu-utilisation",
        "title": "GPU Utilisation & Queue Depth",
        "panels": ["gpu_utilisation_pct", "gpu_memory_used", "gpu_queue_depth", "gpu_temperature"],
        "refresh": "15s",
    },
    "vector_query_p95": {
        "uid": "lis-vector-query-p95",
        "title": "Vector Query P95 Latency",
        "panels": ["vector_query_p95", "vector_query_p50", "hnsw_index_size", "partition_count"],
        "refresh": "30s",
    },
}
```

**Alert Rules Schema:**
```yaml
# config/alertmanager/rules/lis.yml
groups:
  - name: lis_alerts
    rules:
      - alert: SessionFailed
        expr: increase(lis_sessions_failed_total[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Session {{ $labels.session_id }} failed"
          description: "A session has failed. Check pipeline logs."

      - alert: ASRConfidenceDrop
        expr: avg_over_time(lis_asr_confidence_mean[1h]) < 0.6
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "ASR confidence below threshold"
          description: "Mean ASR confidence dropped below 0.6 — possible audio quality regression."

      - alert: GPUUtilisationHigh
        expr: DCGM_FI_DEV_GPU_UTIL > 95
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "GPU utilisation above 95% for 15 minutes"

      - alert: VectorQuerySlow
        expr: histogram_quantile(0.95, lis_vector_query_duration_seconds_bucket) > 0.2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Vector query P95 > 200ms"

      - alert: CostSpike
        expr: lis_cost_total_daily > 50
        for: 0m
        labels:
          severity: info
        annotations:
          summary: "Daily cost exceeded $50 threshold"
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Deploy Prometheus + Grafana + Loki + Tempo via docker-compose | All containers healthy: `docker compose ps` |
| 2 | Deploy dcgm-exporter on GPU host | `nvidia-smi` metrics visible in Prometheus |
| 3 | Deploy postgres-exporter for PG-MAIN and PG-SYLLABUS | `pg_up` metric = 1 in Prometheus |
| 4 | Deploy node-exporter on host | `node_cpu_seconds_total` present |
| 5 | Deploy cAdvisor | Container metrics (`container_cpu_usage_seconds_total`) present |
| 6 | Configure Loki log pipeline for all services | Logs queryable in Grafana Explore |
| 7 | Configure Tempo trace pipeline; instrument API + Prefect + LangGraph | Trace spans visible in Tempo |
| 8 | Deploy GlitchTip for error tracking | Error events appear in GlitchTip |
| 9 | Deploy Uptime Kuma with synthetic checks | Uptime monitors active for all services |
| 10 | Build Dashboard 1: Sessions Funnel | Dashboard renders with live data |
| 11 | Build Dashboard 2: WER Proxy | ASR confidence trend visible |
| 12 | Build Dashboard 3: Cost per Session by Agent | Cost breakdown visible |
| 13 | Build Dashboard 4: A1 Efficiency | Filter discard rate and precision visible |
| 14 | Build Dashboard 5: Topic Health per Subject | Topic counts and stability visible |
| 15 | Build Dashboard 6: GPU Utilisation & Queue Depth | GPU metrics match `nvidia-smi` |
| 16 | Build Dashboard 7: Vector Query P95 | Vector query latency visible |
| 17 | Configure Alertmanager rules and n8n webhook routing | Test alert fires and reaches n8n |
| 18 | Run all T70.x tests | All pass |

**Atomic Sub-tasks:**
1. Infrastructure deployment (Prometheus, Grafana, Loki, Tempo, exporters)
2. Dashboard construction (7 dashboards)
3. Alert rule configuration and n8n routing
4. Trace instrumentation across API → Prefect → LangGraph → model service
5. WER-proxy dashboard with diagnostic value

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| dcgm-exporter fails to start | Fall back to `nvidia-smi` polling via node-exporter textfile collector |
| Loki ingestion exceeds storage | Configure retention policy (30-day default) |
| Tempo trace storage fills up | Reduce trace sampling rate; configure tail-based sampling |
| Grafana dashboard provisioning fails | Validate JSON; check Grafana API health endpoint |
| Alertmanager webhook to n8n fails | Alertmanager retry with exponential backoff; dead-letter queue |
| Prometheus scrape target down | `up` metric goes to 0; Alertmanager fires "target down" alert |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- GitOps-style dashboard provisioning (JSON files in repo, Grafana sidecar loads them)
- Webhook-based alerting (Alertmanager → n8n webhook → notification channels)
- Pull-based metrics collection (Prometheus scrapes exporters)

**Naming & Style Guidelines:**
- Dashboard UIDs: `lis-{dashboard-name}` (lowercase, hyphenated)
- Metric names: `lis_{subsystem}_{metric_name}_{unit}` (Prometheus convention)
- Alert names: PascalCase (e.g., `SessionFailed`, `ASRConfidenceDrop`)
- Log labels: consistent with Prometheus label taxonomy

**Code Splitting Metrics:**
- Dashboard JSON files: max 500 lines each
- Alert rule files: grouped by subsystem
- Docker Compose files: separated by concern (observability stack vs application)

**Type Safety:**
- Dashboard JSON validated via Grafana provisioning API
- Alert rules validated via `amtool check-config`

---

### 5. API & Interface Contracts

**Prometheus Metrics Exposed (by application):**
```
# Session lifecycle
lis_sessions_created_total{subject_id, session_type}
lis_sessions_recording_total
lis_sessions_transcribed_total
lis_sessions_processing_total
lis_sessions_complete_total
lis_sessions_failed_total{error_type}

# ASR quality (WER proxy)
lis_asr_confidence_sum{session_id}
lis_asr_confidence_count{session_id}
lis_asr_confidence_mean = lis_asr_confidence_sum / lis_asr_confidence_count

# Agent cost
lis_agent_runs_total{agent_id, model, outcome}
lis_agent_tokens_input_total{agent_id, model}
lis_agent_tokens_output_total{agent_id, model}
lis_agent_cost_usd_total{agent_id, model}

# A1 efficiency
lis_a1_discard_total{session_id}
lis_a1_retained_total{session_id}
lis_a1_latency_seconds_bucket{le}

# Topic health
lis_topic_count_total{subject_id}
lis_topic_merge_total{subject_id}
lis_topic_split_total{subject_id}

# Vector query
lis_vector_query_duration_seconds_bucket{le, partition_id}
lis_vector_query_total{partition_id, status}

# GPU (via dcgm-exporter)
DCGM_FI_DEV_GPU_UTIL
DCGM_FI_DEV_FB_USED
DCGM_FI_DEV_FB_FREE
DCGM_FI_DEV_TEMPERATURE_GPU
DCGM_FI_DEV_PCIE_TX_THROUGHPUT
```

**Grafana Dashboard Provisioning:**
```yaml
# config/grafana/provisioning/dashboards/dashboards.yml
apiVersion: 1
providers:
  - name: 'LIS Dashboards'
    orgId: 1
    folder: 'LIS'
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

**Alertmanager → n8n Webhook:**
```json
// Alertmanager webhook payload to n8n
{
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "SessionFailed",
        "severity": "critical",
        "session_id": "abc-123"
      },
      "annotations": {
        "summary": "Session abc-123 failed",
        "description": "A session has failed in the processing pipeline."
      },
      "startsAt": "2026-09-12T10:30:00Z",
      "generatorURL": "http://grafana:3000/explore?query=..."
    }
  ]
}
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `PROMETHEUS_URL` | string | Prometheus server URL | `http://prometheus:9090` |
| `GRAFANA_URL` | string | Grafana server URL | `http://grafana:3000` |
| `GRAFANA_API_KEY` | string | Grafana admin API key | `eyJ...` |
| `LOKI_URL` | string | Loki server URL | `http://loki:3100` |
| `TEMPO_URL` | string | Tempo server URL | `http://tempo:3200` |
| `ALERTMANAGER_URL` | string | Alertmanager URL | `http://alertmanager:9093` |
| `N8N_WEBHOOK_URL` | string | n8n webhook for alerts | `https://n8n.example.com/webhook/lis-alerts` |
| `DCGM_EXPORTER_PORT` | int | DCGM exporter port | `9400` |
| `POSTGRES_EXPORTER_MAIN_PORT` | int | PG-MAIN exporter port | `9187` |
| `POSTGRES_EXPORTER_SYLLABUS_PORT` | int | PG-SYLLABUS exporter port | `9188` |

**Docker Compose Services:**
- `prometheus` (port 9090)
- `grafana` (port 3000)
- `loki` (port 3100)
- `tempo` (port 3200)
- `alertmanager` (port 9093)
- `dcgm-exporter` (port 9400)
- `postgres-exporter-main` (port 9187)
- `postgres-exporter-syllabus` (port 9188)
- `node-exporter` (port 9100)
- `cadvisor` (port 8080)
- `glitchtip` (port 8000)
- `uptime-kuma` (port 3001)

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T70.1 | I | Seven dashboards provisioned in Grafana | Grafana loads each dashboard | All seven dashboards render with live data; no "No data" panels |
| T70.2 | I | GPU host running; dcgm-exporter deployed | Query `DCGM_FI_DEV_GPU_UTIL` in Prometheus | GPU metrics present and within ±2% of `nvidia-smi` output |
| T70.3 | I | Alertmanager → n8n webhook configured | Deliberately fail a session (set status=failed) | Alert fires and reaches n8n webhook within 2 minutes |
| T70.4 | I | WER-proxy dashboard deployed; known-good audio baseline | Inject degraded audio (low SNR) into a session | WER-proxy dashboard detects confidence regression; trend line drops |
| T70.5 | I | Sessions with agent_runs cost data exist | Query cost dashboard | Per-session cost queryable and matching `agent_runs` token sums × model pricing |
| T70.6 | I | API + Prefect + LangGraph instrumented with OpenTelemetry | Execute a session end-to-end | Trace spans correlate across API → Prefect → LangGraph → model service in Tempo |

**Verification Commands:**
```bash
# Verify all exporters are up
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health=="up") | .labels.job'

# Verify dashboards
curl -s -H "Authorization: Bearer $GRAFANA_API_KEY" http://localhost:3000/api/search?query=LIS | jq '.[].title'

# Verify alert rules
amtool check-config config/alertmanager/rules/lis.yml

# Verify GPU metrics
curl -s http://localhost:9090/api/v1/query?query=DCGM_FI_DEV_GPU_UTIL | jq '.data.result'

# Full verification
docker compose -f docker/compose/observability/docker-compose.yml ps && \
curl -s http://localhost:9090/-/healthy && \
curl -s http://localhost:3000/api/health | jq .database
```

**Exit Criteria:**
- [ ] All seven dashboards render with live data (T70.1)
- [ ] GPU metrics accurate against `nvidia-smi` (T70.2)
- [ ] Alert fires and reaches n8n within 2 minutes (T70.3)
- [ ] WER-proxy dashboard detects injected audio-quality regression (T70.4)
- [ ] Per-session cost matches `agent_runs` sums (T70.5)
- [ ] Trace spans correlate across the full pipeline (T70.6)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- dcgm-exporter may not work on non-NVIDIA or consumer GPUs; fall back to `nvidia-smi` textfile collector
- Grafana dashboard JSON drift if manually edited; always provision from repo
- Loki log volume can fill disk rapidly; enforce retention policy
- Tempo trace storage is expensive; use tail-based sampling to keep only interesting traces
- Alertmanager silence rules can accidentally suppress critical alerts; audit silences regularly
- n8n webhook may have rate limiting; configure retry and dead-letter in Alertmanager

**Fallback Instructions:**
- If dcgm-exporter fails, use `nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv` with node-exporter textfile collector
- If Grafana provisioning fails, manually import dashboard JSON via UI
- If Alertmanager → n8n fails, fall back to direct email alerts via SMTP
- If Loki storage fills, increase retention or reduce log verbosity

**Rollback Procedure:**
- Docker Compose: `docker compose -f docker/compose/observability/docker-compose.yml down`
- Dashboard: remove provisioned JSON from `config/grafana/dashboards/` and restart Grafana
- Alerts: remove rule files from `config/alertmanager/rules/` and reload Alertmanager
- No database migrations involved; purely infrastructure rollback

---

### 9. Observability (Self-Referential)

**Metrics Added:**
- `lis_observability_stack_up`: Gauge (1 = stack healthy, 0 = degraded)
- `lis_alertmanager_alerts_fired_total`: Counter of alerts fired
- `lis_alertmanager_alerts_resolved_total`: Counter of alerts resolved
- `lis_dashboard_render_success_total`: Counter of successful dashboard renders
- `lis_grafana_api_request_duration_seconds`: Histogram of Grafana API latency

**Tracing/Logging:**
- Span: `observability.dashboard_render` for dashboard provisioning
- Span: `observability.alert_fire` for alert routing
- Log event: `observability_stack_deployed` with component list
- Log event: `alert_fired` with alertname, severity, labels
- Log event: `alert_resolved` with alertname, resolution_time

**Alerts:**
- Alert if any exporter is down for > 5 minutes
- Alert if Grafana health check fails
- Alert if Loki ingestion rate drops to zero
- Alert if Tempo trace ingestion fails

---

### 10. Exit Checklist

- [ ] All tests pass (T70.1, T70.2, T70.3, T70.4, T70.5, T70.6)
- [ ] Seven dashboards render with live data
- [ ] GPU metrics accurate against `nvidia-smi`
- [ ] Alert fires and reaches n8n within 2 minutes
- [ ] WER-proxy dashboard has diagnostic value (not decoration)
- [ ] Per-session cost queryable and accurate
- [ ] Trace spans correlate across full pipeline
- [ ] Alertmanager rules validated with `amtool`
- [ ] Observability stack health is itself observable
