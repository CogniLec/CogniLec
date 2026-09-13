#!/usr/bin/env python3
"""S04: Populate manifest with sample session data for testing/development.

Creates 6 sample sessions covering the full condition matrix.
Audio files are NOT created — only the manifest entries.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

MANIFEST_PATH = Path("lis-eval/phase0/v1/manifest.json")

SAMPLE_SESSIONS = [
    {
        "session_id": "sess_20260911_001",
        "room": "Room 101",
        "device": "iPhone 15",
        "position": "front_row",
        "condition": "front_quiet",
        "subject": "CS101",
        "consent_id": "consent_001",
    },
    {
        "session_id": "sess_20260911_002",
        "room": "Room 101",
        "device": "Zoom H1n",
        "position": "back_row",
        "condition": "back_quiet",
        "subject": "CS101",
        "consent_id": "consent_002",
    },
    {
        "session_id": "sess_20260912_001",
        "room": "Room 203",
        "device": "Blue Yeti USB Mic",
        "position": "front_row",
        "condition": "front_busy",
        "subject": "MATH201",
        "consent_id": "consent_003",
    },
    {
        "session_id": "sess_20260912_002",
        "room": "Room 203",
        "device": "iPhone 15",
        "position": "back_row",
        "condition": "back_busy",
        "subject": "MATH201",
        "consent_id": "consent_004",
    },
    {
        "session_id": "sess_20260913_001",
        "room": "Room 105",
        "device": "Zoom H1n",
        "position": "front_row",
        "condition": "lecturer_moving",
        "subject": "PHYS101",
        "consent_id": "consent_005",
    },
    {
        "session_id": "sess_20260913_002",
        "room": "Room 101",
        "device": "Blue Yeti USB Mic",
        "position": "front_row",
        "condition": "heavy_discussion",
        "subject": "CS101",
        "consent_id": "consent_006",
    },
]


def main() -> None:
    base_time = datetime(2026, 9, 11, 9, 0, 0)

    sessions = []
    for i, sample in enumerate(SAMPLE_SESSIONS):
        session_time = base_time + timedelta(days=i // 2, hours=(i % 2) * 2)
        sessions.append(
            {
                **sample,
                "timestamp": session_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration_seconds": 3600,
                "audio_file": f"{sample['session_id']}/audio.opus",
                "audio_size_bytes": 14234567,
                "audio_duration_seconds": 3612,
                "audio_sample_rate": 48000,
                "audio_channels": 1,
                "audio_codec": "opus",
            }
        )

    manifest = {
        "version": "1.0",
        "phase": "phase0",
        "sessions": sessions,
    }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Populated manifest with {len(sessions)} sample sessions:")
    for s in sessions:
        print(f"  {s['session_id']}: {s['condition']} ({s['room']})")


if __name__ == "__main__":
    main()
