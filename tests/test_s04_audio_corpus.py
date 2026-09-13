"""S04 — Real-Environment Audio Corpus verification tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "lis-eval" / "phase0" / "v1" / "manifest.json"

VALID_CONDITIONS = {
    "front_quiet",
    "back_quiet",
    "front_busy",
    "back_busy",
    "lecturer_moving",
    "heavy_discussion",
}

REQUIRED_MANIFEST_FIELDS = [
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


class TestDirectoryStructure:
    """Verify lis-eval directory layout per spec."""

    @pytest.mark.unit
    def test_lis_eval_directory_exists(self) -> None:
        assert ROOT.joinpath("lis-eval").is_dir()

    @pytest.mark.unit
    def test_phase0_v1_directory_exists(self) -> None:
        assert ROOT.joinpath("lis-eval", "phase0", "v1").is_dir()

    @pytest.mark.unit
    def test_manifest_file_exists(self) -> None:
        assert MANIFEST.is_file()


class TestManifestSchema:
    """Verify manifest.json follows the spec schema."""

    @staticmethod
    def _load_manifest() -> dict[str, Any]:
        with MANIFEST.open() as f:
            return json.load(f)  # type: ignore[no-any-return]

    @pytest.mark.unit
    def test_manifest_is_valid_json(self) -> None:
        assert isinstance(self._load_manifest(), dict)

    @pytest.mark.unit
    def test_manifest_version(self) -> None:
        assert self._load_manifest().get("version") == "1.0"

    @pytest.mark.unit
    def test_manifest_phase(self) -> None:
        assert self._load_manifest().get("phase") == "phase0"

    @pytest.mark.unit
    def test_manifest_has_sessions_key(self) -> None:
        data = self._load_manifest()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    @pytest.mark.unit
    def test_all_sessions_have_required_fields(self) -> None:
        data = self._load_manifest()
        for i, session in enumerate(data["sessions"]):
            for field in REQUIRED_MANIFEST_FIELDS:
                assert field in session, f"Session {i} missing field '{field}'"

    @pytest.mark.unit
    def test_session_ids_are_unique(self) -> None:
        data = self._load_manifest()
        ids = [s["session_id"] for s in data["sessions"]]
        assert len(ids) == len(set(ids)), "Duplicate session_id found"

    @pytest.mark.unit
    def test_conditions_are_valid(self) -> None:
        data = self._load_manifest()
        for session in data["sessions"]:
            assert session["condition"] in VALID_CONDITIONS, (
                f"Invalid condition '{session['condition']}' in {session['session_id']}"
            )

    @pytest.mark.unit
    def test_consent_ids_present(self) -> None:
        data = self._load_manifest()
        for session in data["sessions"]:
            consent_id = session.get("consent_id")
            assert consent_id and consent_id != "null", (
                f"Missing consent_id in {session['session_id']}"
            )

    @pytest.mark.unit
    def test_audio_codec_is_opus(self) -> None:
        data = self._load_manifest()
        for session in data["sessions"]:
            assert session["audio_codec"] == "opus", (
                f"audio_codec should be 'opus' in {session['session_id']}"
            )

    @pytest.mark.unit
    def test_audio_sample_rate_48k(self) -> None:
        data = self._load_manifest()
        for session in data["sessions"]:
            assert session["audio_sample_rate"] == 48000, (
                f"audio_sample_rate should be 48000 in {session['session_id']}"
            )

    @pytest.mark.unit
    def test_audio_channels_mono(self) -> None:
        data = self._load_manifest()
        for session in data["sessions"]:
            assert session["audio_channels"] == 1, (
                f"audio_channels should be 1 (mono) in {session['session_id']}"
            )

    @pytest.mark.unit
    def test_audio_file_paths(self) -> None:
        data = self._load_manifest()
        for session in data["sessions"]:
            assert session["audio_file"].endswith("/audio.opus"), (
                f"audio_file should end with '/audio.opus' in {session['session_id']}"
            )


class TestConditionMatrix:
    """Verify the condition matrix is covered (T04.3)."""

    @staticmethod
    def _load_manifest() -> dict[str, Any]:
        with MANIFEST.open() as f:
            return json.load(f)  # type: ignore[no-any-return]

    @pytest.mark.unit
    def test_all_conditions_represented(self) -> None:
        data = self._load_manifest()
        covered = {s["condition"] for s in data["sessions"]}
        missing = VALID_CONDITIONS - covered
        assert not missing, f"Missing conditions: {missing}"

    @pytest.mark.unit
    def test_session_count_at_least_six(self) -> None:
        data = self._load_manifest()
        assert len(data["sessions"]) >= 6, (
            f"Need at least 6 sessions to cover all conditions, got {len(data['sessions'])}"
        )


class TestConsentForm:
    """Verify consent form template exists and has required content."""

    @pytest.mark.unit
    def test_consent_form_exists(self) -> None:
        assert ROOT.joinpath("docs", "consent-form.md").is_file()

    @pytest.mark.unit
    def test_consent_form_has_purpose(self) -> None:
        content = ROOT.joinpath("docs", "consent-form.md").read_text()
        assert "speech recognition" in content.lower() or "topic modeling" in content.lower()

    @pytest.mark.unit
    def test_consent_form_has_deletion_policy(self) -> None:
        content = ROOT.joinpath("docs", "consent-form.md").read_text()
        assert "deleted" in content.lower() or "deletion" in content.lower()

    @pytest.mark.unit
    def test_consent_form_has_withdrawal_rights(self) -> None:
        content = ROOT.joinpath("docs", "consent-form.md").read_text()
        assert "withdraw" in content.lower() or "delete" in content.lower()

    @pytest.mark.unit
    def test_consent_form_has_signature_fields(self) -> None:
        content = ROOT.joinpath("docs", "consent-form.md").read_text()
        assert "signature" in content.lower()


class TestScripts:
    """Verify S04 scripts exist and are executable."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "script_name",
        [
            "s04_init_dvc.sh",
            "s04_upload_to_minio.sh",
            "s04_convert_to_opus.sh",
            "s04_create_bucket.sh",
            "s04_create_session.sh",
            "s04_add_session_to_manifest.sh",
            "s04_list_sessions.sh",
            "s04_validate_manifest.py",
            "s04_populate_sample_data.py",
            "verify_s04.sh",
        ],
    )
    def test_script_exists(self, script_name: str) -> None:
        script_path = ROOT.joinpath("scripts", script_name)
        assert script_path.is_file(), f"Missing script: {script_name}"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "script_name",
        [
            "s04_init_dvc.sh",
            "s04_upload_to_minio.sh",
            "s04_convert_to_opus.sh",
            "s04_create_bucket.sh",
            "s04_create_session.sh",
            "s04_add_session_to_manifest.sh",
            "s04_list_sessions.sh",
            "s04_validate_manifest.py",
            "s04_populate_sample_data.py",
            "verify_s04.sh",
        ],
    )
    def test_script_is_executable(self, script_name: str) -> None:
        script_path = ROOT.joinpath("scripts", script_name)
        assert script_path.stat().st_mode & 0o111, f"Script not executable: {script_name}"


class TestEnvConfig:
    """Verify .env.example has DVC/MinIO config for S04."""

    @pytest.mark.unit
    def test_dvc_remote_var(self) -> None:
        content = ROOT.joinpath(".env.example").read_text()
        assert "DVC_REMOTE" in content

    @pytest.mark.unit
    def test_aws_credentials_for_dvc(self) -> None:
        content = ROOT.joinpath(".env.example").read_text()
        assert "AWS_ACCESS_KEY_ID" in content
        assert "AWS_SECRET_ACCESS_KEY" in content
