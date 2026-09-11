# S04 — Real-Environment Audio Corpus
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Record 8–10 real lectures in target rooms with actual devices, capturing diverse acoustic conditions, with consent and metadata, stored in MinIO and versioned with DVC.

**Component Boundaries:**
- **Allowed:** Recording devices, consent forms, MinIO `lis-eval` bucket, DVC remote, metadata manifest
- **Off-limits:** Transcription (S05), ASR models (S06), preprocessing pipeline (S17)

**Tech Stack:**
| Tool | Version | Purpose |
|------|---------|---------|
| Recording Device | Any (phone, USB mic, Zoom H1n) | Capture audio |
| Opus Encoder | libopus 1.5+ | 48kHz mono, ~15MB/60min |
| MinIO Client (mc) | Latest | Upload to `lis-eval` |
| DVC | 3.52.x | Version control for data |
| Consent Form | `docs/consent-form.md` | GDPR-compliant |

---

### 2. State Machine & Domain Schemas

**Session Metadata Schema (`lis-eval/phase0/v1/manifest.json`):**
```json
{
  "version": "1.0",
  "phase": "phase0",
  "sessions": [
    {
      "session_id": "sess_20260911_001",
      "timestamp": "2026-09-11T09:00:00Z",
      "room": "Room 101",
      "device": "iPhone 15 / USB Mic / Zoom H1n",
      "position": "front_row",
      "duration_seconds": 3600,
      "subject": "CS101",
      "condition": "quiet_monologue",
      "consent_id": "consent_001",
      "audio_file": "sess_20260911_001/audio.opus",
      "audio_size_bytes": 14234567,
      "audio_duration_seconds": 3612,
      "audio_sample_rate": 48000,
      "audio_channels": 1,
      "audio_codec": "opus"
    }
  ]
}
```

**Condition Matrix (must cover all):**
| Condition ID | Description | Target Sessions |
|--------------|-------------|-----------------|
| `front_quiet` | Front row, quiet room, lecturer stationary | 1-2 |
| `back_quiet` | Back row, quiet room, lecturer stationary | 1-2 |
| `front_busy` | Front row, busy room (HVAC, hallway noise) | 1 |
| `back_busy` | Back row, busy room | 1 |
| `lecturer_moving` | Lecturer walks around, varying distance | 1 |
| `heavy_discussion` | Student Q&A, multiple speakers, overlapping | 1-2 |

**Consent Form Fields (`docs/consent-form.md`):**
- Participant name (optional, for records only)
- Date, room, session ID
- Purpose: "Audio recording for LIS research (speech recognition, topic modeling)"
- Data stored: "Encrypted MinIO bucket, deleted after 30 days post-processing"
- Rights: "Withdraw consent anytime; data deleted on request"
- Signature + date

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Details |
|------|--------|---------|
| 1 | Prepare consent forms | Print `docs/consent-form.md` x 10 |
| 2 | Scout rooms | Test acoustic conditions; note HVAC, windows, seating |
| 3 | Select devices | Phone (Voice Memos), USB mic (Blue Yeti), or Zoom H1n |
| 4 | Record session | Start recording -> lecture -> stop; verify playback |
| 5 | Convert to Opus | `ffmpeg -i input.wav -c:a libopus -b:a 24k -ac 1 -ar 48000 output.opus` |
| 6 | Upload to MinIO | `mc cp output.opus local/lis-eval/phase0/v1/{session_id}/audio.opus` |
| 7 | Write metadata | Create `manifest.json` entry |
| 8 | DVC add + push | `dvc add lis-eval/phase0/v1/ && dvc push` |
| 9 | Store consent | Scan/photo consent form -> secure storage (not repo) |
| 10 | Verify | `dvc checkout` reproduces byte-identical |

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Recording failed (battery, storage) | Re-record; mark session void in manifest |
| Consent refused | Exclude session; do not upload |
| Audio corrupted | Verify playback immediately; re-record if needed |
| Room unavailable | Substitute similar condition; document in manifest |
| DVC push fails | Check MinIO creds; `dvc remote modify` |

---

### 4. Code Style & Architecture Constraints

- **Audio format:** Opus, 48kHz, mono, ~24 kbps (<=15MB for 60 min)
- **File naming:** `{session_id}/audio.opus` (flat in session dir)
- **Metadata:** JSON manifest at root; one entry per session
- **DVC remote:** MinIO `lis-eval` bucket (configured in S03)
- **Consent:** GDPR-compliant; no PII in metadata beyond `consent_id`
- **No speaker identity** in metadata (NFR-S4)

---

### 5. API & Interface Contracts

**MinIO Upload (via `mc` or presigned URL from S14):**
```bash
# Direct mc upload
mc cp audio.opus local/lis-eval/phase0/v1/sess_001/audio.opus

# Presigned URL (from S14 API)
curl -X PUT -H "Content-Type: audio/opus" \
  --data-binary @audio.opus \
  "https://minio.lis.local/lis-eval/phase0/v1/sess_001/audio.opus?X-Amz-Signature=..."
```

**DVC Commands:**
```bash
dvc init
dvc remote add -d origin s3://lis-eval
dvc remote modify origin endpointurl http://minio:9000
dvc remote modify origin access_key_id minioadmin
dvc remote modify origin secret_access_key minioadmin
dvc add lis-eval/phase0/v1/
dvc push
```

**Metadata Manifest Structure:**
```
lis-eval/phase0/v1/
├── manifest.json
├── sess_001/
│   └── audio.opus
├── sess_002/
│   └── audio.opus
└── ...
```

---

### 6. Dependency & Environment Configuration

**Required `.env` for DVC/MinIO:**
```bash
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=changeme
DVC_REMOTE=s3://lis-eval
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=changeme
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
```

**Recording Device Settings:**
| Device | App | Settings |
|--------|-----|----------|
| iPhone | Voice Memos | Lossless (or 44.1kHz) |
| Android | Recorder | High quality |
| USB Mic | Audacity/OBS | 48kHz, mono, WAV |
| Zoom H1n | Built-in | 48kHz, WAV |

---

### 7. Definition of Done & Verification

**Test Matrix:**
| Test ID | Type | Verification |
|---------|------|--------------|
| T04.1 | M | Each session: metadata complete + consent form signed/scanned |
| T04.2 | U | `dvc checkout` -> `sha256sum` matches original for all files |
| T04.3 | M | Condition matrix covered: front/back, quiet/busy, stationary/moving, discussion |

**Verification Script (`scripts/verify_s04.sh`):**
```bash
#!/bin/bash
set -euo pipefail

echo "=== Verifying S04 Audio Corpus ==="

# 1. DVC reproducibility
dvc pull
echo "DVC pull complete"

# 2. Check manifest exists
MANIFEST="lis-eval/phase0/v1/manifest.json"
if [ ! -f "$MANIFEST" ]; then
    echo "FAIL: manifest.json missing"
    exit 1
fi
echo "Manifest found"

# 3. Verify each session
SESSION_COUNT=$(jq '.sessions | length' "$MANIFEST")
echo "Sessions recorded: $SESSION_COUNT"

for i in $(seq 0 $((SESSION_COUNT-1))); do
    SESSION_ID=$(jq -r ".sessions[$i].session_id" "$MANIFEST")
    AUDIO_FILE="lis-eval/phase0/v1/$SESSION_ID/audio.opus"

    if [ ! -f "$AUDIO_FILE" ]; then
        echo "FAIL: Missing audio for $SESSION_ID"
        exit 1
    fi

    # Verify Opus file
    DURATION=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$AUDIO_FILE")
    echo "  $SESSION_ID: ${DURATION}s"

    # Check consent_id present
    CONSENT_ID=$(jq -r ".sessions[$i].consent_id" "$MANIFEST")
    if [ "$CONSENT_ID" = "null" ] || [ -z "$CONSENT_ID" ]; then
        echo "FAIL: Missing consent_id for $SESSION_ID"
        exit 1
    fi
done

# 4. Check condition coverage
CONDITIONS=$(jq -r '.sessions[].condition' "$MANIFEST" | sort -u)
echo "Conditions covered: $CONDITIONS"
REQUIRED=("front_quiet" "back_quiet" "front_busy" "back_busy" "lecturer_moving" "heavy_discussion")
for req in "${REQUIRED[@]}"; do
    if ! echo "$CONDITIONS" | grep -q "$req"; then
        echo "WARN: Missing condition: $req"
    fi
done

echo "=== S04 VERIFIED ==="
```

---

### 8. Failure Modes & Self-Correction

| Failure | Detection | Correction |
|---------|-----------|------------|
| Audio quality poor (clipping, noise) | Playback review; `ffprobe` stats | Re-record with gain adjustment; different position |
| Consent form incomplete | Manual review | Re-contact participant; exclude if unresolved |
| DVC push fails | `dvc push` error | Check MinIO creds; bucket exists; network |
| Condition not covered | `verify_s04.sh` warns | Schedule additional recording session |
| Device storage full | Recording stops early | Monitor during recording; offload between sessions |
| Opus conversion fails | `ffmpeg` error | Check libopus installed; try different bitrate |
