# S03 — Core Infrastructure Compose Stack
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Deploy the complete local infrastructure stack via docker-compose: dual PostgreSQL, PgBouncer, Valkey, MinIO, pgAdmin, Traefik (mkcert TLS), Dozzle, Portainer, Label Studio, MLflow — with internal network isolation and SOPS-managed secrets.

**Component Boundaries:**
- **Allowed:** `docker-compose.yml`, `docker/postgres/*.conf`, `docker/postgres/init-*.sql`, `docker/pgbouncer/*`, `docker/minio/buckets.sh`, `docker/pgadmin/servers.json`, `docker/traefik/certs/*`, `docker/label-studio/projects/`, `.sops.yaml`, `secrets/*.txt` (encrypted)
- **Off-limits:** Application code, GPU Dockerfiles (S02), ML models (S06+)

**Tech Stack & Version Pinning:**
| Service | Image | Version |
|---------|-------|---------|
| PG-MAIN | `pgvector/pgvector` | pg17 |
| PG-SYLLABUS | `postgres` | 17 |
| PgBouncer | `edoburu/pgbouncer` | 1.23 |
| Valkey | `valkey/valkey` | 8-alpine |
| MinIO | `minio/minio` | latest |
| pgAdmin | `dpage/pgadmin4` | 8 |
| Traefik | `traefik` | v3.0 |
| Dozzle | `amir20/dozzle` | latest |
| Portainer | `portainer/portainer-ce` | 2.25 |
| Label Studio | `heartexlabs/label-studio` | 1.12.0 |
| MLflow | `python` | 3.12-slim (installs mlflow 2.16.2) |

---

### 2. State Machine & Domain Schemas

**Network Topology:**
```
internal (no egress)          edge (ingress only)
├── pg-main:5432              ├── traefik:80/443/8080
├── pg-syllabus:5432          ├── pgbouncer:6432
├── pgbouncer:6432            ├── minio:9000/9001
├── valkey:6379               ├── pgadmin:5050
├── minio:9000                ├── dozzle:8080
├── label-studio:8080         ├── portainer:9000
├── mlflow:5000               └── label-studio:8080
└── models (volume)           └── mlflow:5000
```

**Volume Mounts:**
| Volume | Mount Point | Purpose |
|--------|-------------|---------|
| `models` | `/models` | Shared HF model cache |
| `pg-main-data` | `/var/lib/postgresql/data` | PG-MAIN persistence |
| `pg-syllabus-data` | `/var/lib/postgresql/data` | PG-SYLLABUS persistence |
| `valkey-data` | `/data` | Valkey persistence |
| `minio-data` | `/data` | MinIO persistence |
| `pgadmin-data` | `/var/lib/pgadmin` | pgAdmin config |
| `label-studio-data` | `/label-studio/data` | Label Studio annotations |
| `traefik-letsencrypt` | `/letsencrypt` | ACME certificates |

**Secrets (SOPS-encrypted in `secrets/`):**
| Secret File | Used By | Description |
|-------------|---------|-------------|
| `pg_main_password.txt` | pg-main, pgbouncer, MLflow | PG-MAIN password |
| `pg_syllabus_password.txt` | pg-syllabus | PG-SYLLABUS password |
| `minio_root_user.txt` | MinIO, MLflow | MinIO access key |
| `minio_root_password.txt` | MinIO, MLflow | MinIO secret key |
| `pgadmin_email.txt` | pgAdmin | Admin email |
| `pgadmin_password.txt` | pgAdmin | Admin password |
| `label_studio_user.txt` | Label Studio | Admin user |
| `label_studio_password.txt` | Label Studio | Admin password |

**PG-MAIN Config (`docker/postgres/main.conf`):** Key settings from spec.

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Command |
|------|--------|---------|
| 1 | Generate mkcert certs | `mkcert -install && mkcert -cert-file docker/traefik/certs/cert.pem -key-file docker/traefik/certs/key.pem lis.local "*.lis.local" localhost 127.0.0.1 ::1` |
| 2 | Generate age keys | `age-keygen -o age.key && mv age.key.pub .sops.pub` |
| 3 | Create SOPS config | Write `.sops.yaml` with age public keys |
| 4 | Encrypt secrets | `sops -e -i secrets/pg_main_password.txt` (etc.) |
| 5 | Write docker-compose.yml | Full stack per spec |
| 6 | Write PG configs | `docker/postgres/main.conf`, `syllabus.conf` |
| 7 | Write init SQLs | `docker/postgres/init-main.sql`, `init-syllabus.sql` |
| 8 | Write PgBouncer config | `docker/pgbouncer/pgbouncer.ini`, `userlist.txt` |
| 9 | Write MinIO bucket init | `docker/minio/buckets.sh` (executable) |
| 10 | Write pgAdmin servers | `docker/pgadmin/servers.json` |
| 11 | Write Label Studio projects | `docker/label-studio/projects/*.json` (3 projects) |
| 12 | Start stack | `docker compose up -d` |
| 13 | Verify all healthy | `docker compose ps` + health checks |
| 14 | Verify internal network isolation | `docker run --rm --network lis-internal curlimages/curl:latest curl -f http://google.com` → should fail |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Port conflicts (5432, 6379, 9000) | Stop local services; use `docker compose down -v` |
| pgvector extension missing | Use `pgvector/pgvector:pg17` image |
| Traefik certs not trusted | Run `mkcert -install` on host; browser restart |
| SOPS decrypt fails | Verify age private key in keyring; `sops -d secrets/...` |
| Label Studio DB migration | Wait for SQLite init; check logs |
| MLflow artifact upload fails | Check MinIO bucket `lis-eval` exists; S3 creds |

---

### 4. Code Style & Architecture Constraints

- **Internal network = no egress:** Enforced by Docker `internal: true`; verified by test
- **PG-MAIN ≠ PG-SYLLABUS:** Separate containers, volumes, networks; FDW for cross-DB reads
- **PgBouncer only for PG-MAIN:** PG-SYLLABUS accessed directly (low traffic)
- **Secrets via SOPS+age:** Never plaintext in repo; age public keys committed, private in 1Password
- **Traefik TLS:** mkcert for local dev; production uses Let's Encrypt
- **Healthchecks:** All services must have `healthcheck` with `start_period`
- **Resource limits:** Memory limits per service (see compose)

---

### 5. API & Interface Contracts

**Service Endpoints (via Traefik):**
| Service | Hostname | Port | Auth |
|---------|----------|------|------|
| pgAdmin | `pgadmin.lis.local` | 443 | Email/password |
| MinIO Console | `minio.lis.local` | 443 | Access/secret key |
| Label Studio | `label.lis.local` | 443 | User/password |
| MLflow | `mlflow.lis.local` | 443 | None (local) |
| Dozzle | `logs.lis.local` | 443 | None |
| Portainer | `portainer.lis.local` | 443 | Admin setup |
| Traefik Dashboard | `traefik.lis.local` | 443 | None |

**Direct Access (internal network):**
| Service | Host:Port | Protocol |
|---------|-----------|----------|
| PG-MAIN | pg-main:5432 | PostgreSQL |
| PG-SYLLABUS | pg-syllabus:5432 | PostgreSQL |
| PgBouncer | pgbouncer:6432 | PostgreSQL (pooled) |
| Valkey | valkey:6379 | Redis/Valkey |
| MinIO API | minio:9000 | S3 |

**MinIO Bucket Scheme (from `buckets.sh`):**
```
lis-audio/           # Raw audio chunks (ILM: 30 days post-complete)
lis-uploads/         # Client uploads (permanent)
lis-generated/       # Generated assets (permanent)
lis-exports/         # User exports (ILM: 7 days)
lis-eval/            # Eval data + MLflow artifacts (permanent, versioned)
```

---

### 6. Dependency & Environment Configuration

**`.env` (from `.env.example`):**
```bash
DOMAIN=lis.local
TRAEFIK_EMAIL=admin@lis.local
POSTGRES_USER=lis
POSTGRES_PASSWORD=changeme
POSTGRES_DB=lis_main
SYLLABUS_DB=lis_syllabus
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=changeme
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=changeme
MINIO_SECURE=false
VALKEY_PASSWORD=changeme
PGADMIN_EMAIL=admin@lis.local
PGADMIN_PASSWORD=changeme
LABEL_STUDIO_USER=admin@lis.local
LABEL_STUDIO_PASSWORD=changeme
SECRET_KEY=changeme_generate_with_openssl_rand_hex_32
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
HF_HOME=/models/huggingface
```

**SOPS Config (`.sops.yaml`):**
```yaml
creation_rules:
  - path_regex: \.env\.(prod|staging|local)$
    encrypted_regex: ^(.*_PASSWORD|.*_SECRET|.*_KEY|.*_TOKEN)$
    age: >
      age1xxxx..., age1yyyy...
  - path_regex: secrets/.*\.txt$
    encrypted_regex: ^.*
    age: >
      age1xxxx...
```

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T03.1 | I | `docker compose up -d && sleep 30 && docker compose ps --format json` | All services `healthy` |
| T03.2 | I | `docker exec lis-pg-main psql -U lis -d lis_main -c "CREATE EXTENSION vector; CREATE EXTENSION pg_partman;"` | Both succeed |
| T03.3 | I | Open pgAdmin UI | Lists "PG-MAIN" and "PG-SYLLABUS" servers |
| T03.4 | S | `docker run --rm --network lis-internal curlimages/curl curl -f http://google.com` | **Fails** (no egress) |
| T03.5 | I | `mc alias set local http://minio:9000 ... && mc mb local/test && mc rm local/test` | Round-trip succeeds |
| T03.6 | I | `curl -k https://lis.local` | Returns Traefik 404 (TLS works) |
| T03.7 | I | `curl -k https://label.lis.local` | Label Studio login page |
| T03.8 | I | `curl -k https://mlflow.lis.local` | MLflow UI |

**Verification Script (`scripts/verify_s03.sh`):**
```bash
#!/bin/bash
set -euo pipefail
docker compose up -d
echo "Waiting for services..."
sleep 30

# Check all healthy
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}"

# PG extensions
docker exec lis-pg-main psql -U lis -d lis_main -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_partman;"

# Internal network isolation
if docker run --rm --network lis-internal curlimages/curl:latest curl -sf http://google.com >/dev/null 2>&1; then
    echo "FAIL: internal network has egress"
    exit 1
else
    echo "PASS: internal network no egress"
fi

# MinIO
docker exec lis-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec lis-minio mc ls local/

# TLS
curl -kf https://lis.local >/dev/null && echo "TLS OK"

# Label Studio
curl -kf https://label.lis.local >/dev/null && echo "Label Studio OK"

# MLflow
curl -kf https://mlflow.lis.local >/dev/null && echo "MLflow OK"

echo "=== S03 VERIFIED ==="
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| Service stuck `starting` | `docker compose ps` shows unhealthy | Check logs: `docker compose logs <service>`; usually dependency not ready |
| PG extension missing | `CREATE EXTENSION` fails | Use `pgvector/pgvector:pg17` image; check `shared_preload_libraries` |
| Traefik certs invalid | Browser shows "Not Secure" | Re-run `mkcert`; ensure certs in `docker/traefik/certs/`; restart Traefik |
| SOPS decrypt fails | `sops -d` errors | Verify age private key available; check `.sops.yaml` age recipients |
| MinIO bucket not created | `mc ls` empty | Run `buckets.sh` manually; check MinIO logs |
| Label Studio 500 | UI shows error | Check SQLite permissions; `chown -R 1000:1000 label-studio-data/` |
| MLflow DB connection fails | MLflow UI shows error | Check PG-MAIN ready; MLflow `backend-store-uri` correct |
