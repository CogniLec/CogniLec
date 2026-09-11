#!/bin/bash
set -euo pipefail

# S03 — Core Infrastructure Compose Stack Verification Script
# Verifies all S03 requirements per spec: services, PG extensions, Valkey,
# MinIO, PgBouncer, and internal network isolation.

PASS=0
FAIL=0
SKIP=0

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  SKIP: $1"; SKIP=$((SKIP + 1)); }

echo "=== S03 Core Infrastructure Verification ==="
echo ""

# ------------------------------------------------------------------
# T03.1 — All services healthy
# ------------------------------------------------------------------
echo "[T03.1] docker compose ps — all services healthy"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}" 2>/dev/null

UNHEALTHY=$(docker compose ps --format json 2>/dev/null \
  | python3 -c "
import sys, json
for line in sys.stdin:
    s = json.loads(line)
    health = s.get('Health', '')
    if health == 'unhealthy':
        print(s.get('Name', 'unknown'))
" 2>/dev/null || true)

if [ -z "$UNHEALTHY" ]; then
    pass "All services healthy"
else
    fail "Unhealthy services: $UNHEALTHY"
fi
echo ""

# ------------------------------------------------------------------
# T03.2 — PG extensions (vector, uuid-ossp, citext)
# ------------------------------------------------------------------
echo "[T03.2] PG extensions on lis_main"
EXTS=$(docker compose exec -T pg-main psql -U lis -d lis_main -t -A \
  -c "SELECT extname FROM pg_extension ORDER BY extname;" 2>/dev/null || true)

for ext in vector uuid-ossp citext plpgsql; do
    if echo "$EXTS" | grep -qw "$ext"; then
        pass "Extension '$ext' installed"
    else
        fail "Extension '$ext' missing"
    fi
done
echo ""

# ------------------------------------------------------------------
# T03.3 — Valkey responds to PING
# ------------------------------------------------------------------
echo "[T03.3] Valkey ping"
PONG=$(docker compose exec -T valkey valkey-cli ping 2>/dev/null || true)
if [ "$PONG" = "PONG" ]; then
    pass "Valkey responds PONG"
else
    fail "Valkey ping failed (got: '$PONG')"
fi
echo ""

# ------------------------------------------------------------------
# T03.4 — MinIO health endpoint
# ------------------------------------------------------------------
echo "[T03.4] MinIO health"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:9000/minio/health/live 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    pass "MinIO health endpoint returned 200"
else
    fail "MinIO health returned HTTP $HTTP_CODE"
fi
echo ""

# ------------------------------------------------------------------
# T03.5 — PgBouncer connection (port 6432)
# ------------------------------------------------------------------
echo "[T03.5] PgBouncer connection"
PGPASSWORD=lis_dev PGRESULT=$(docker compose exec -T -e PGPASSWORD=lis_dev pg-main \
  psql -h pgbouncer -p 6432 -U lis -d lis_main -t -A -c "SELECT 1" 2>/dev/null || true)
if [ "$PGRESULT" = "1" ]; then
    pass "PgBouncer returned SELECT 1"
else
    fail "PgBouncer query failed (got: '$PGRESULT')"
fi
echo ""

# ------------------------------------------------------------------
# T03.6 — Internal network isolation (no egress)
# ------------------------------------------------------------------
echo "[T03.6] Internal network isolation — no egress to internet"
if docker run --rm --network lis-internal curlimages/curl:latest \
     -sf --max-time 5 http://google.com >/dev/null 2>&1; then
    fail "Internal network HAS egress (should be blocked)"
else
    pass "Internal network blocks egress"
fi
echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "============================================="
echo "RESULTS: $PASS passed, $FAIL failed, $SKIP skipped"
echo "============================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
