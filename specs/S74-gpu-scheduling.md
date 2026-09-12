# S74 — GPU Scheduling & Training Isolation
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Prevent training runs from starving live serving by implementing MIG partitioning on A100/H100-class hardware (or scheduled training windows plus hard GPU-affinity assignment on smaller GPUs), KEDA scale-to-zero for bursty services (image-generation, OCR workers), and Ray Serve for multi-host multiplexing if needed.

**Component Boundaries:**
- **Allowed:** `docker/compose/gpu/`, `config/gpu/`, `config/keda/`, `config/ray/`, `scripts/gpu/`, `tests/`
- **Off-limits:** Application source code, database schemas, agent logic, model training code

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| NVIDIA Container Toolkit | 1.16.x | GPU container allocation |
| MIG Manager | 1.16.x | Multi-Instance GPU partitioning |
| KEDA | 2.14.x | Event-driven autoscaling (scale-to-zero) |
| Ray Serve | 2.9.x | Multi-host GPU serving (if needed) |
| Kubernetes | 1.30.x | Container orchestration (for KEDA/Ray) |
| Docker Compose | 2.x | Local deployment |

---

### 2. State Machine & Domain Schemas

**GPU Resource Allocation:**
```
idle -> allocated_serving -> (release -> idle)
                          -> (allocate_training -> serving + training)
                          -> (training_complete -> allocated_serving)
```

**MIG Partition Strategy (A100/H100):**
```
A100 80GB:
  - 7x GPU instances (1g.10gb) for serving
  - 1x GPU instance (3g.40gb) for training
  - OR: 3x GPU instances (3g.20gb) balanced

Quadro T1000 Mobile 4GB:
  - No MIG support
  - Time-sharing: training windows during off-hours
  - Hard GPU-affinity: training job pinned to specific GPU via CUDA_VISIBLE_DEVICES
```

**Training Window Schedule:**
```yaml
# config/gpu/training_windows.yaml
training_windows:
  - name: "overnight"
    start: "02:00"
    end: "06:00"
    timezone: "UTC"
    allowed_tasks: ["fine_tune", "re_embed", "re_cluster"]
  - name: "weekend"
    start: "sat 00:00"
    end: "sun 23:59"
    timezone: "UTC"
    allowed_tasks: ["fine_tune", "re_embed", "re_cluster", "reprocessing"]
```

**KEDA ScaledObject Configuration:**
```yaml
# config/keda/scaled-objects.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: image-gen-worker
spec:
  scaleTargetRef:
    name: image-gen-worker
  minReplicaCount: 0
  maxReplicaCount: 5
  triggers:
    - type: rabbitmq
      metadata:
        queueName: image-gen-tasks
        queueLength: "1"
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: ocr-worker
spec:
  scaleTargetRef:
    name: ocr-worker
  minReplicaCount: 0
  maxReplicaCount: 3
  triggers:
    - type: rabbitmq
      metadata:
        queueName: ocr-tasks
        queueLength: "1"
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Assess GPU hardware and determine MIG vs time-sharing strategy | Strategy documented based on GPU class |
| 2 | Configure MIG partitions (if A100/H100) | `nvidia-smi mig` shows correct partitions |
| 3 | Configure GPU-affinity assignment for training jobs | Training job runs on designated GPU only |
| 4 | Configure training windows for non-MIG GPUs | Training only runs during allowed windows |
| 5 | Deploy KEDA with image-gen and OCR scaled objects | Workers scale to 0 when idle |
| 6 | Test scale-to-zero: image-gen worker wakes on demand | Cold-start within acceptable time |
| 7 | Test training isolation: fine-tuning job during live serving | ASR latency not degraded beyond NFR-P1 |
| 8 | Test GPU memory isolation: training cannot claim serving memory | Training job fails if serving memory reserved |
| 9 | Configure service start order after host reboot | Services start in correct order |
| 10 | Measure GPU utilisation during idle periods | Utilisation drops measurably |
| 11 | Evaluate Ray Serve for multi-host multiplexing (if needed) | Decision documented |
| 12 | Run all T74.x tests | All pass |

**Atomic Sub-tasks:**
1. GPU hardware assessment and MIG configuration
2. Training window scheduling
3. GPU-affinity assignment for training jobs
4. KEDA deployment and scale-to-zero configuration
5. Service start order enforcement
6. GPU utilisation monitoring

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| MIG not supported on GPU | Fall back to time-sharing with training windows |
| Training job exceeds window | Kill training job; defer to next window |
| KEDA fails to scale to 0 | Manual scale-down; investigate trigger configuration |
| Training job claims serving GPU | CUDA_VISIBLE_DEVICES enforcement; cgroup limits |
| Cold-start too slow | Pre-warm containers; keep minimum replicas |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- MIG partitioning pattern (hardware-level isolation)
- Time-sharing pattern (software-level scheduling)
- Event-driven autoscaling (KEDA)
- Graceful degradation (training yields to serving)

**Naming & Style Guidelines:**
- GPU config: `config/gpu/`
- KEDA manifests: `config/keda/`
- Ray config: `config/ray/`
- GPU scripts: `scripts/gpu/`

**Code Splitting Metrics:**
- GPU config files: max 100 lines each
- KEDA manifests: max 50 lines each
- GPU scripts: max 80 lines each

**Type Safety:**
- GPU device IDs validated before assignment
- Training window times validated with timezone awareness
- KEDA trigger metadata typed

---

### 5. API & Interface Contracts

**GPU Status Query:**
```bash
# Query GPU status
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv

# Query MIG instances
nvidia-smi mig -lgi

# Query GPU process isolation
nvidia-smi --query-compute-apps=pid,process_name,gpu_uuid,used_memory --format=csv
```

**GPU Affinity Configuration:**
```bash
# Pin training job to GPU 1
CUDA_VISIBLE_DEVICES=1 python train.py --config lora_config.yaml

# Verify isolation
nvidia-smi --query-compute-apps=pid,process_name,gpu_uuid --format=csv
```

**Service Start Order Configuration:**
```yaml
# config/gpu/start_order.yaml
service_start_order:
  - name: "nvidia-driver"
    timeout_s: 30
  - name: "nvidia-container-toolkit"
    depends_on: "nvidia-driver"
    timeout_s: 10
  - name: "pg-main"
    timeout_s: 30
  - name: "minio"
    timeout_s: 30
  - name: "vllm-serving"
    depends_on: ["pg-main", "nvidia-container-toolkit"]
    gpu_affinity: "0"
    timeout_s: 120
  - name: "asr-worker"
    depends_on: ["pg-main", "vllm-serving"]
    gpu_affinity: "0"
    timeout_s: 60
  - name: "prefect-worker"
    depends_on: ["pg-main", "minio"]
    timeout_s: 30
  - name: "api"
    depends_on: ["pg-main", "minio", "vllm-serving"]
    timeout_s: 30
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `GPU_COUNT` | int | Number of GPUs available | `1` |
| `GPU_TYPE` | string | GPU model | `Quadro T1000 Mobile` |
| `GPU_VRAM_MB` | int | GPU VRAM in MB | `4096` |
| `MIG_ENABLED` | bool | Whether MIG is enabled | `false` |
| `TRAINING_WINDOW_START` | string | Training window start time | `02:00` |
| `TRAINING_WINDOW_END` | string | Training window end time | `06:00` |
| `SERVING_GPU_IDS` | string | GPU IDs reserved for serving | `0` |
| `TRAINING_GPU_IDS` | string | GPU IDs available for training | `1` |
| `KEDA_ENABLED` | bool | Enable KEDA autoscaling | `true` |
| `IMAGE_GEN_MIN_REPLICAS` | int | Min replicas for image-gen worker | `0` |
| `IMAGE_GEN_MAX_REPLICAS` | int | Max replicas for image-gen worker | `5` |
| `OCR_MIN_REPLICAS` | int | Min replicas for OCR worker | `0` |
| `OCR_MAX_REPLICAS` | int | Max replicas for OCR worker | `3` |

**Docker Compose Services:**
- `nvidia-device-plugin` (Kubernetes) or `nvidia-smi` (Docker)
- `keda-operator` (if using KEDA)
- `ray-head` (if using Ray Serve)
- `ray-worker` (if using Ray Serve)

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T74.1 | I | Fine-tuning job running on training GPU; live ASR serving on serving GPU | Process live audio while training runs concurrently | ASR latency not degraded beyond NFR-P1 (real-time factor < 1.0 maintained) |
| T74.2 | I | Image-gen worker scaled to 0; queue has pending task | Task arrives in queue | Worker scales from 0 to 1 within acceptable cold-start time (< 30s) |
| T74.3 | I | Serving GPU memory fully allocated to serving processes | Training job attempts to allocate GPU memory | Training job fails with out-of-memory; serving continues unaffected |
| T74.4 | I | Host fully rebooted | System starts up | Services start in correct order (S36 T36.2 regression test) |
| T74.5 | P | All serving processes idle; no training scheduled | Measure GPU utilisation over 5-minute window | GPU utilisation drops measurably (cost/power validation) |

**Verification Commands:**
```bash
# Verify GPU status
nvidia-smi

# Verify MIG partitions (if applicable)
nvidia-smi mig -lgi

# Verify GPU affinity
nvidia-smi --query-compute-apps=pid,process_name,gpu_uuid --format=csv

# Verify KEDA scaling
kubectl get scaledobject image-gen-worker -o yaml

# Verify service start order
docker compose ps --format "table {{.Name}}\t{{.Status}}"

# Full verification
nvidia-smi && \
docker compose -f docker/compose/gpu/docker-compose.yml ps && \
uv run pytest tests/ -m integration -v -k "S74 or gpu_scheduling"
```

**Exit Criteria:**
- [ ] Fine-tuning job running concurrently does not degrade live ASR beyond NFR-P1 (T74.1)
- [ ] Image-gen worker scales to zero and wakes on demand (T74.2)
- [ ] Training job cannot claim GPU memory reserved for serving (T74.3)
- [ ] Service start order enforced after full host reboot (T74.4)
- [ ] GPU utilisation during idle periods drops measurably (T74.5)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- MIG not available on consumer GPUs; fall back to time-sharing
- CUDA_VISIBLE_DEVICES can be bypassed by some frameworks; use cgroup limits as safety net
- KEDA cold-start may be slow for large models; pre-warm or keep minimum replicas
- Training window timezone errors can cause training to run during serving hours
- Ray Serve adds complexity; only use if multi-host is actually needed

**Fallback Instructions:**
- If MIG fails, fall back to time-sharing with strict training windows
- If KEDA fails, manually scale workers and investigate trigger config
- If GPU isolation fails, kill training job and investigate cgroup config
- If cold-start too slow, keep minimum 1 replica for critical services

**Rollback Procedure:**
- MIG: `nvidia-smi mig -dgi` to destroy instances; revert to monolithic GPU
- KEDA: `kubectl delete scaledobject` to remove autoscaling; set fixed replicas
- Training windows: revert `config/gpu/training_windows.yaml`
- Service start order: revert `config/gpu/start_order.yaml`

---

### 9. Observability (if applicable)

**Metrics Added:**
- `lis_gpu_utilisation_pct{gpu_id}`: Gauge of GPU utilisation per GPU
- `lis_gpu_memory_used_mb{gpu_id}`: Gauge of GPU memory used per GPU
- `lis_gpu_temperature_c{gpu_id}`: Gauge of GPU temperature per GPU
- `lis_gpu_process_count{gpu_id, type}`: Gauge of GPU processes (serving vs training)
- `lis_gpu_training_active`: Gauge (1 if training running, 0 otherwise)
- `lis_keda_replicas{service}`: Gauge of KEDA-managed replica count
- `lis_keda_scale_events_total{service, direction}`: Counter of scale up/down events
- `lis_service_start_order_violations_total`: Counter of start order violations

**Tracing/Logging:**
- Span: `gpu.training_job_start` for training job launch
- Span: `gpu.training_job_complete` for training job completion
- Log event: `gpu_allocation` with gpu_id, process_type, memory_mb
- Log event: `gpu_deallocation` with gpu_id, process_type
- Log event: `keda_scale_up` with service, current_replicas, desired_replicas
- Log event: `keda_scale_down` with service, current_replicas, desired_replicas
- Log event: `training_window_started` with window_name
- Log event: `training_window_ended` with window_name

**Alerts:**
- Alert if training job runs outside allowed window
- Alert if GPU utilisation > 95% for > 15 minutes
- Alert if KEDA fails to scale to 0
- Alert if service start order violated
- Alert if training job claims serving GPU memory

---

### 10. Exit Checklist

- [ ] All tests pass (T74.1, T74.2, T74.3, T74.4, T74.5)
- [ ] Training and serving coexist without contention
- [ ] MIG or time-sharing configured correctly
- [ ] KEDA scale-to-zero working for bursty services
- [ ] GPU memory isolation verified
- [ ] Service start order enforced after reboot
- [ ] GPU utilisation drops during idle periods
- [ ] Training and serving isolation documented
