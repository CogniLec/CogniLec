#!/usr/bin/env python3
"""S04: Validate manifest.json against the spec schema."""

import json
import sys
from pathlib import Path

REQUIRED_FIELDS = [
    "session_id",
    "timestamp",
    "room",
    "device",
    "position",
    "duration_seconds",
    "subject",
    "condition",
    "consent_id",
    "audio_file",
    "audio_size_bytes",
    "audio_duration_seconds",
    "audio_sample_rate",
    "audio_channels",
    "audio_codec",
]

VALID_CONDITIONS = {
    "front_quiet",
    "back_quiet",
    "front_busy",
    "back_busy",
    "lecturer_moving",
    "heavy_discussion",
}

MANIFEST_PATH = Path("lis-eval/phase0/v1/manifest.json")


def validate_manifest() -> list[str]:
    errors: list[str] = []

    if not MANIFEST_PATH.exists():
        return [f"Manifest not found: {MANIFEST_PATH}"]

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    # Check top-level fields
    if manifest.get("version") != "1.0":
        errors.append(f"Invalid version: {manifest.get('version')} (expected '1.0')")
    if manifest.get("phase") != "phase0":
        errors.append(f"Invalid phase: {manifest.get('phase')} (expected 'phase0')")

    sessions = manifest.get("sessions", [])
    if not sessions:
        errors.append("No sessions in manifest")

    seen_ids: set[str] = set()
    seen_conditions: set[str] = set()

    for i, session in enumerate(sessions):
        sid = session.get("session_id", f"<missing index {i}>")
        prefix = f"Session {i} ({sid})"

        # Check required fields
        for field in REQUIRED_FIELDS:
            if field not in session:
                errors.append(f"{prefix}: Missing field '{field}'")

        # Check unique session_id
        if sid in seen_ids:
            errors.append(f"{prefix}: Duplicate session_id")
        seen_ids.add(sid)

        # Check condition is valid
        cond = session.get("condition", "")
        if cond not in VALID_CONDITIONS:
            errors.append(f"{prefix}: Invalid condition '{cond}' (valid: {VALID_CONDITIONS})")
        seen_conditions.add(cond)

        # Check consent_id is present and non-null
        consent_id = session.get("consent_id")
        if not consent_id or consent_id == "null":
            errors.append(f"{prefix}: Missing or null consent_id")

        # Check audio_file path
        audio_file = session.get("audio_file", "")
        if not audio_file.endswith("/audio.opus"):
            errors.append(f"{prefix}: audio_file should end with '/audio.opus'")

        # Check numeric fields
        for num_field in [
            "duration_seconds",
            "audio_size_bytes",
            "audio_duration_seconds",
            "audio_sample_rate",
            "audio_channels",
        ]:
            val = session.get(num_field)
            if val is None:
                errors.append(f"{prefix}: Missing numeric field '{num_field}'")
            elif not isinstance(val, int | float):
                errors.append(
                    f"{prefix}: Field '{num_field}' should be numeric, got {type(val).__name__}"
                )

        # Check audio codec
        if session.get("audio_codec") != "opus":
            errors.append(f"{prefix}: audio_codec should be 'opus'")

        # Check audio sample rate
        if session.get("audio_sample_rate") != 48000:
            errors.append(f"{prefix}: audio_sample_rate should be 48000")

        # Check audio channels
        if session.get("audio_channels") != 1:
            errors.append(f"{prefix}: audio_channels should be 1 (mono)")

    # Check condition coverage
    missing_conditions = VALID_CONDITIONS - seen_conditions
    if missing_conditions:
        print(f"WARNING: Missing conditions: {', '.join(missing_conditions)}")

    return errors


def main() -> int:
    errors = validate_manifest()
    if errors:
        print("VALIDATION FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    else:
        print("Manifest validation PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
