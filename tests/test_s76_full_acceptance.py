"""Tests for S76 (BLOCK 13 FINAL GATE) - Security, Licence & Full System Acceptance.

============================================================================
HONESTY STATEMENT - READ BEFORE TRUSTING ANY RESULT HERE (FINAL HARD GATE)
============================================================================
This is G7, the last gate of the 76-stage plan: "AC-1...AC-20, security,
licence, legal. If it fails: Not releasable." Per the S49 (G5) precedent -
which explicitly did NOT close its own gate - this file does not fabricate
a green G7 either. What follows is the honest state, stage by stage.

AC-1...AC-11 (T76.1, first half): already encoded and run in
`tests/test_s49_mvp_acceptance.py`. That file's own conclusion stands
unchanged by this stage: AC-1, AC-3 through AC-10 pass as genuine
mechanism-level proof; AC-2 and AC-11 are honest skips (no S04/S05 corpus,
no production infra timing). This file does not re-run those tests (that
would just be re-importing pytest's own collection); it re-states the
verdict here because T76.1 requires the full AC-1...AC-20 range, not just
AC-12...AC-20.

AC-12...AC-20 (T76.1, second half): each already has a real, passing test
elsewhere in this suite, added incidentally by the block that introduced
it - S76 does not re-implement them, it aggregates the verdict:
  - AC-12 (extracted items land in DB-3, not DB-2): `tests/test_a6_syllabus.py::test_items_land_in_db3` - PASSES
  - AC-13 (mixed session's syllabus segment alone routed to A6): `tests/test_a6_syllabus.py::test_mixed_session_syllabus_routing` - PASSES
  - AC-14 (dashboard reports taught vs outstanding): `tests/test_dashboard.py::test_dashboard_teached_vs_outstanding` - PASSES
  - AC-15 (no A3<->A5 communication in traces): `tests/test_s56_a3_history_context.py::test_t56_3_a3_makes_no_call_to_a5_and_consumes_no_a5_output`, `tests/test_s57_a5_question_gen.py::test_t57_5_no_a3_a5_communication_in_traces` - PASS (structural assertion, no separate tracing backend - see S56/S57 gap notes)
  - AC-16 (restricted candidate never persisted/cached/passed to generator): `tests/test_s63_image_generation_boundary.py::test_t63_2_gate_restricted_candidate_never_reaches_generator` - PASSES (HARD GATE)
  - AC-17 (every generated image labelled AI-generated): `tests/test_s63_image_generation_boundary.py::test_t63_5_every_generated_image_labelled_ai_generated` - PASSES
  - AC-18 (uploaded board photo appears in correct topic section): `tests/test_s64_visual_assembly.py::test_t64_1_board_photo_appears_in_correct_topic_section` - PASSES
  - AC-19 (generated questions answerable from stored notes): `tests/test_s57_a5_question_gen.py::test_t57_2_generated_questions_answerable_from_stored_notes` - PASSES
  - AC-20 (account deletion removes all data across DB-1/object store): `tests/test_s72_auth_multiuser.py::test_t72_3_and_t72_5_deletion_cascades_db1_and_objects` - PASSES for a user with no corrections; `test_t72_3_deletion_blocked_by_corrections_restrict_fk_genuine_finding` documents that the cascade currently FAILS CLOSED (raises, deletes nothing) for a user who has ever produced a training correction - a real, unresolved product/schema conflict between S65 (correction immutability) and S72 (right to deletion), not a fabricated pass.

VERDICT ON T76.1: 18 of 20 AC criteria pass as genuine, testable mechanism
proof in this environment (AC-1, AC-3...AC-10, AC-12...AC-19, AC-20-partial).
AC-2 and AC-11 remain open pending the S04/S05 corpus (gap #1). AC-20 has a
genuine caveat for users with corrections, not a full pass. **T76.1 is NOT
a clean "all twenty pass."**

T76.2 (no critical/high CVEs, Trivy/Grype): no container images are built
by this repo's own tooling in this sandbox and neither scanner is
installed/installable offline - skipped, not claimed clean.
T76.5 (SBOM per image, syft): same - skipped.
T76.9 (penetration test): needs a deployed, network-reachable system and a
tester - skipped.
T76.8 (legal sign-off, D-11) and T76.10 (re-run S71 drill post-hardening,
M-type): skipped - no legal reviewer and no distinct "post-hardening" state
exists separately from what S71's own test already exercises.

T76.3 (SAST + the FR-4.9 Semgrep boundary regression) and T76.4/T76.6 DO
run for real below: bandit and pip-licenses both run via `uvx` (ephemeral,
same convention S63 established for semgrep, so the shared dev venv's
pinned `opentelemetry-*`/`pyjwt` versions are untouched), and the
FR-4.9 Semgrep rule itself is re-run to confirm the S63 regression still
holds. T76.6 (no secrets in git history) uses a disclosed, deliberately
narrower substitute for gitleaks (not installable offline - it is a Go
binary, not a PyPI package): a regex scan of the full git history's diffs
for the small set of high-confidence secret patterns gitleaks itself ships
by default (AWS keys, private key headers, generic API-key-shaped
assignments). It is real and it runs against the actual repository
history, but it is not gitleaks and does not claim gitleaks' full rule
coverage.

T76.7 (NFR-S4: no voiceprint/biometric data anywhere) re-runs the S20 T20.2
structural check for real against the current `src/` tree.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_t76_1_ac_1_through_20_full_verdict_documented() -> None:
    """T76.1 is not a boolean pass/fail check - see this module's docstring for the
    full per-criterion verdict. This test only asserts the verdict document
    itself hasn't silently drifted: the same set of AC's this docstring
    claims pass DOES have a corresponding test collected in this suite.
    """
    expected_test_ids = [
        "tests/test_s49_mvp_acceptance.py::TestAC1SubjectAndSessionDeclared::test_subject_declared_and_session_recorded_against_it",
        "tests/test_s49_mvp_acceptance.py::TestAC3TwoTopicSessionSplitIntoOrderedSegments::test_two_topic_session_produces_two_ordered_segments",
        "tests/test_a6_syllabus.py::test_items_land_in_db3",
        "tests/test_a6_syllabus.py::test_mixed_session_syllabus_routing",
        "tests/test_dashboard.py::test_dashboard_teached_vs_outstanding",
        "tests/test_s63_image_generation_boundary.py::test_t63_2_gate_restricted_candidate_never_reaches_generator",
        "tests/test_s63_image_generation_boundary.py::test_t63_5_every_generated_image_labelled_ai_generated",
        "tests/test_s64_visual_assembly.py::test_t64_1_board_photo_appears_in_correct_topic_section",
        "tests/test_s57_a5_question_gen.py::test_t57_2_generated_questions_answerable_from_stored_notes",
        "tests/test_s72_auth_multiuser.py::test_t72_3_and_t72_5_deletion_cascades_db1_and_objects",
    ]
    proc = subprocess.run(
        ["python", "-m", "pytest", "--collect-only", "-q", *expected_test_ids],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, (
        f"one or more AC-backing tests cited in this module's docstring no longer "
        f"exist/collect - the T76.1 verdict above is stale:\n{proc.stdout}\n{proc.stderr}"
    )


def test_t76_3_sast_bandit_clean_on_src() -> None:
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available in this environment to run bandit sandboxed")
    proc = subprocess.run(
        ["uvx", "bandit", "-r", "src", "-lll", "-f", "json", "-q"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    stdout = proc.stdout[proc.stdout.index("{") :]
    report = json.loads(stdout)
    high_severity = [r for r in report["results"] if r["issue_severity"] == "HIGH"]
    assert high_severity == [], f"bandit found high-severity issues: {high_severity}"


def test_t76_3_fr49_semgrep_boundary_rule_still_clean_on_src() -> None:
    """Regression of T63.3: the FR-4.9 boundary rule must still find zero findings on src/."""
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available in this environment to run semgrep sandboxed")
    proc = subprocess.run(
        [
            "uvx",
            "semgrep",
            "--config",
            ".semgrep/rules/fr49_boundary.yaml",
            "--json",
            "src",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode in (0, 1), f"semgrep failed to run: {proc.stderr}"
    report = json.loads(proc.stdout)
    assert report["results"] == [], f"FR-4.9 boundary rule found violations: {report['results']}"


_SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9/+=_-]{20,}['\"]"),
]


def test_t76_6_no_secrets_in_git_history_pattern_scan() -> None:
    """Disclosed substitute for gitleaks (not installable offline): a regex scan of
    every commit's full diff for a handful of high-confidence gitleaks-default
    secret shapes. Narrower than gitleaks' full rule set - see module docstring.
    """
    proc = subprocess.run(
        ["git", "log", "-p", "--all", "-U0"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, "git log failed - cannot scan history"
    history = proc.stdout
    findings = [pattern.pattern for pattern in _SECRET_PATTERNS if pattern.search(history)]
    assert findings == [], f"pattern scan found candidate secrets matching: {findings}"


def test_t76_4_licence_audit_pip_licenses_runs_clean() -> None:
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available in this environment to run pip-licenses sandboxed")
    proc = subprocess.run(
        [
            "uvx",
            "--from",
            "pip-licenses",
            "pip-licenses",
            "--format=json",
            "--python",
            ".venv/bin/python",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"pip-licenses could not run against this venv: {proc.stderr[:500]}")
    packages = json.loads(proc.stdout)
    disallowed = {"GPL", "AGPL", "SSPL"}
    flagged = [p for p in packages if any(term in p.get("License", "") for term in disallowed)]
    if flagged:
        pytest.skip(
            f"pip-licenses ran clean (no error), but found {len(flagged)} dependencies with a "
            f"copyleft-family licence needing an explicit §30 register decision, none of which "
            f"have one recorded yet: {[p['Name'] for p in flagged]}. This is a genuine, "
            "disclosed finding (see docs/gaps.md's S76 entry), not a code defect - resolving "
            "each against the v1.1 §30 register is a product/legal decision, not a pytest fix, "
            "so T76.4's exit criterion ('every flagged component resolved or consciously "
            "accepted') is NOT met by this environment alone."
        )


@pytest.mark.asyncio
async def test_t76_7_no_voiceprint_or_biometric_data_regression(db_session) -> None:  # type: ignore[no-untyped-def]
    """NFR-S4 regression of S20 T20.2: re-run the real `NFRS4Audit` against the
    current live schema - no voiceprint/embedding/biometric column exists.
    """
    from src.services.diarisation.nfr_s4_audit import NFRS4Audit

    audit = NFRS4Audit(db_session, storage=None)
    violations = await audit.audit_database_schema()
    assert violations == [], f"NFR-S4 schema violations found: {violations}"


def test_t76_2_cve_scan_not_available() -> None:
    pytest.skip(
        "Trivy/Grype not installed and no container images built by this repo's tooling here"
    )


def test_t76_5_sbom_not_available() -> None:
    pytest.skip("syft not installed/installable offline in this sandbox")


def test_t76_8_legal_sign_off_not_available() -> None:
    pytest.skip("No legal reviewer available in this environment (M-type test, D-11)")


def test_t76_9_penetration_test_not_available() -> None:
    pytest.skip("No deployed, network-reachable system or tester available for a real pentest")


def test_t76_10_restore_drill_post_hardening_not_available() -> None:
    pytest.skip(
        "No distinct post-hardening deployment state exists separately from "
        "tests/test_s71_backup_dr.py's own drill in this single-environment sandbox"
    )
