# S76 — Security, Licence & Full System Acceptance (FINAL GATE)
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** Execute the full acceptance run — all twenty AC tests (AC-1 through AC-20) must pass, security and licence audits must be clean, and legal sign-off must be recorded. This is the FINAL HARD GATE (G7). The system is not releasable until this stage passes completely.

**Component Boundaries:**
- **Allowed:** `tests/acceptance/`, `tests/security/`, `scripts/security/`, `scripts/licence/`, `docs/security/`, `docs/legal/`, `config/security/`
- **Off-limits:** Application source code (audit only, no modifications unless fixing findings), database schemas, model training code

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| Trivy | 0.55.x | Container image vulnerability scanning |
| Grype | 0.80.x | Container image vulnerability scanning (alternative) |
| Semgrep | 1.80.x | SAST (static application security testing) |
| Bandit | 1.8.x | Python SAST |
| gitleaks | 8.18.x | Secret detection in git history |
| syft | 1.10.x | SBOM generation |
| pip-licenses | 4.x | Python licence audit |
| OWASP ZAP | 2.15.x | API penetration testing |
| pytest | 8.x | Acceptance test runner |
| Locust | 2.x | Load testing (NFR-P7 re-verification) |

---

### 2. State Machine & Domain Schemas

**Acceptance Gate Lifecycle:**
```
pending -> scanning -> testing -> auditing -> reviewing -> (passed | failed)
                                                        -> (remediation -> scanning)
```

**Security Scan Results Schema:**
```python
class SecurityScanResult(BaseModel):
    scan_type: str  # trivy, grype, semgrep, bandit, gitleaks, zap
    scan_target: str  # image_name, source_dir, repo_url
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    findings: list[SecurityFinding] = []
    scan_time_s: float
    passed: bool  # True if no critical/high findings


class SecurityFinding(BaseModel):
    severity: str  # critical, high, medium, low, info
    rule_id: str
    description: str
    file_path: str | None = None
    line_number: int | None = None
    remediation: str | None = None
    cve_id: str | None = None
    cvss_score: float | None = None


class LicenceAuditResult(BaseModel):
    component: str
    version: str
    licence: str
    status: str  # approved, flagged, denied
    decision: str | None = None  # recorded decision for flagged items
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class AcceptanceTestResult(BaseModel):
    ac_id: str  # AC-1 through AC-20
    test_id: str  # T76.x
    status: str  # passed, failed, skipped
    description: str
    evidence: str | None = None
    regression_of: str | None = None  # if this is a regression test


class LegalSignoff(BaseModel):
    signoff_type: str  # recording_consent, data_privacy, licence_compliance
    signed_by: str
    signed_at: datetime
    document_ref: str  # reference to signed document
    notes: str | None = None
```

**AC Test Mapping (all 20):**
```
AC-1:  Subject declared, session recorded against it       (S49 T49.1)
AC-2:  60-min lecture -> complete transcript, WER within gate (S49 T49.2)
AC-3:  Two-topic session split into two ordered segments   (S49 T49.3)
AC-4:  Topic across three sessions recognised as one       (S49 T49.4)
AC-5:  Off-topic chatter excluded; relevant question retained (S49 T49.5)
AC-6:  Notes post-session only; no DB-2 row without DB-1   (S49 T49.6)
AC-7:  Every note section traces to source utterances       (S49 T49.7)
AC-8:  Primary LLM killed -> completes via fallback        (S49 T49.8)
AC-9:  All tiers exhausted -> failed, fully reprocessable   (S49 T49.9)
AC-10: No cross-subject retrieval                          (S49 T49.10)
AC-11: Processing < 15 min P90                             (S49 T49.11)
AC-12: Syllabus items land in DB-3, not DB-2               (S50 T50.2)
AC-13: Mixed session syllabus segment routed to A6         (S50 T50.6)
AC-14: Dashboard correctly reports taught vs outstanding    (S52 T52.2)
AC-15: No A3<->A5 communication in traces                  (S57 T57.5)
AC-16: Restricted candidate image never persisted           (S63 T63.2)
AC-17: Generated images labelled AI-generated               (S63 T63.5)
AC-18: Uploaded board photo appears in correct topic section (S64 T64.1)
AC-19: Generated questions answerable from stored notes     (S57 T57.2)
AC-20: Account deletion removes all data across all stores  (S72 T72.3)
```

**Regression Tests Re-run at S76:**
```
T20.2: No voiceprint/biometric data anywhere (NFR-S4)
T36.2: Service start order after reboot
T42.4: No core content discarded by A1
T31.3: User-edited topic labels preserved
T63.3: FR-4.9 Semgrep boundary rule present
T12.1: RLS isolation (user A cannot see user B data)
T12.2: RLS isolation (user B cannot see user A data)
```

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Run Trivy scan on all shipped images | No critical/high CVEs unresolved |
| 2 | Run Grype scan on all shipped images (cross-validation) | Results consistent with Trivy |
| 3 | Run Semgrep SAST on entire codebase | Clean; FR-4.9 boundary rule present |
| 4 | Run Bandit SAST on Python codebase | Clean; no high-severity findings |
| 5 | Run gitleaks on full git history | No secrets detected |
| 6 | Generate SBOM per image using syft | SBOM stored per image |
| 7 | Run pip-licenses against §30 licence register | All components approved or decisions recorded |
| 8 | Run syft licence scan (cross-validation) | Consistent with pip-licenses |
| 9 | Execute all 20 AC tests (T76.1) | All pass |
| 10 | Re-run 7 regression tests | All pass |
| 11 | Run NFR-S4 verification (no voiceprint/biometric) | Clean |
| 12 | Execute penetration test of API surface | Findings triaged |
| 13 | Re-execute restore drill (S71) | Pass |
| 14 | Document legal review of recording consent (D-11) | Legal sign-off recorded |
| 15 | Compile security report | Report complete |
| 16 | Compile licence audit report | Report complete |
| 17 | Final gate decision | ALL criteria met |

**Atomic Sub-tasks:**
1. Security scanning (Trivy, Grype, Semgrep, Bandit, gitleaks)
2. SBOM generation and storage
3. Licence audit against §30 register
4. AC test execution (all 20)
5. Regression test re-run (7 tests)
6. NFR-S4 verification
7. Penetration testing
8. Restore drill re-execution
9. Legal review and sign-off
10. Final report compilation

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| Critical CVE found in shipped image | Block release; upgrade dependency; re-scan |
| SAST finding in production code | Block release; fix or document accepted risk |
| Secret found in git history | Block release; rotate secret; scrub history |
| AC test fails | Block release; fix test or fix system |
| Licence audit finds unapproved component | Block release; get legal decision or replace component |
| Legal sign-off not received | Block release; complete legal review |
| Restore drill fails | Block release; fix backup/restore process |
| Penetration test finds critical vulnerability | Block release; fix vulnerability; re-test |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- Gate pattern (hard stop; all criteria must pass)
- Audit pattern (immutable records of all scans and decisions)
- Regression pattern (re-run known-good assertions)
- Evidence pattern (all findings documented with evidence)

**Naming & Style Guidelines:**
- Security scans: `tests/security/`
- AC tests: `tests/acceptance/`
- Reports: `docs/security/`
- Legal docs: `docs/legal/`
- SBOM storage: `sbom/` directory

**Code Splitting Metrics:**
- AC test files: max 200 lines each
- Security scan scripts: max 100 lines each
- Reports: max 50 pages each

**Type Safety:**
- All scan results typed with Pydantic models
- All AC test results typed
- All legal sign-offs typed

---

### 5. API & Interface Contracts

**Security Scan Scripts:**
```bash
# Trivy image scan
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-api:latest
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-worker:latest

# Grype image scan (cross-validation)
grype lis-api:latest --fail-on critical
grype lis-worker:latest --fail-on critical

# Semgrep SAST
semgrep scan --config auto --severity ERROR src/

# Bandit SAST
bandit -r src/ -ll --format json --output bandit-report.json

# gitleaks history scan
gitleaks detect --source . --report-format json --report-path gitleaks-report.json

# SBOM generation
syft lis-api:latest -o spdx-json=sbom/lis-api-sbom.json
syft lis-worker:latest -o spdx-json=sbom/lis-worker-sbom.json

# Licence audit
pip-licenses --format=json --output-file licences/pip-licenses.json
syft lis-api:latest -o spdx-json=sbom/lis-api-sbom.json | jq '.packages[].licenseDeclared'
```

**AC Test Suite (pytest):**
```python
# tests/acceptance/test_ac_suite.py
import pytest


class TestACSuite:
    """Full acceptance criteria test suite — ALL must pass for G7."""

    @pytest.mark.acceptance
    def test_ac_01_subject_session_recorded(self, deployment):
        """AC-1: Subject declared, session recorded against it."""

    @pytest.mark.acceptance
    def test_ac_02_transcript_wer(self, deployment):
        """AC-2: 60-min lecture -> complete transcript, WER within S06 gate."""

    @pytest.mark.acceptance
    def test_ac_03_topic_split(self, deployment):
        """AC-3: Two-topic session split into two ordered segments."""

    @pytest.mark.acceptance
    def test_ac_04_topic_identity(self, deployment):
        """AC-4: Topic across three sessions recognised as one."""

    @pytest.mark.acceptance
    def test_ac_05_filter_retention(self, deployment):
        """AC-5: Off-topic chatter excluded; relevant student question retained."""

    @pytest.mark.acceptance
    def test_ac_06_post_session_only(self, deployment):
        """AC-6: Notes post-session only; no DB-2 row without DB-1."""

    @pytest.mark.acceptance
    def test_ac_07_source_tracing(self, deployment):
        """AC-7: Every note section traces to source utterances and timestamps."""

    @pytest.mark.acceptance
    def test_ac_08_fallback(self, deployment):
        """AC-8: Primary LLM killed -> completes via fallback."""

    @pytest.mark.acceptance
    def test_ac_09_tiers_exhausted(self, deployment):
        """AC-9: All tiers exhausted -> failed, fully reprocessable."""

    @pytest.mark.acceptance
    def test_ac_10_no_cross_subject(self, deployment):
        """AC-10: No cross-subject retrieval."""

    @pytest.mark.acceptance
    def test_ac_11_processing_time(self, deployment):
        """AC-11: Processing < 15 min P90."""

    @pytest.mark.acceptance
    def test_ac_12_syllabus_db3(self, deployment):
        """AC-12: Syllabus items land in DB-3, not DB-2."""

    @pytest.mark.acceptance
    def test_ac_13_mixed_session_routing(self, deployment):
        """AC-13: Mixed session syllabus segment routed to A6."""

    @pytest.mark.acceptance
    def test_ac_14_coverage_dashboard(self, deployment):
        """AC-14: Dashboard correctly reports taught vs outstanding."""

    @pytest.mark.acceptance
    def test_ac_15_no_a3_a5_communication(self, deployment):
        """AC-15: No A3<->A5 communication in traces."""

    @pytest.mark.acceptance
    def test_ac_16_image_boundary(self, deployment):
        """AC-16: Restricted candidate image never persisted."""

    @pytest.mark.acceptance
    def test_ac_17_ai_generated_label(self, deployment):
        """AC-17: Generated images labelled AI-generated."""

    @pytest.mark.acceptance
    def test_ac_18_board_photo_routing(self, deployment):
        """AC-18: Uploaded board photo appears in correct topic section."""

    @pytest.mark.acceptance
    def test_ac_19_question_answerable(self, deployment):
        """AC-19: Generated questions answerable from stored notes."""

    @pytest.mark.acceptance
    def test_ac_20_deletion_cascade(self, deployment):
        """AC-20: Account deletion removes all data across all stores."""
```

**Regression Test Suite (re-run at S76):**
```python
# tests/acceptance/test_regression_suite.py
class TestRegressionSuite:
    """Regression tests that must pass at S76 gate."""

    @pytest.mark.regression
    def test_t20_2_no_biometric_data(self, deployment):
        """NFR-S4: No voiceprint or biometric data anywhere in system."""

    @pytest.mark.regression
    def test_t36_2_service_start_order(self, deployment):
        """Service start order after full host reboot."""

    @pytest.mark.regression
    def test_t42_4_no_content_discarded(self, deployment):
        """A1 discard precision > 0.90; zero core content discarded."""

    @pytest.mark.regression
    def test_t31_3_label_preservation(self, deployment):
        """User-edited topic labels preserved during re-cluster."""

    @pytest.mark.regression
    def test_t63_3_boundary_rule(self, deployment):
        """FR-4.9 Semgrep boundary rule present and passing."""

    @pytest.mark.regression
    def test_t12_1_rls_isolation_a(self, deployment):
        """RLS: User A cannot see User B data."""

    @pytest.mark.regression
    def test_t12_2_rls_isolation_b(self, deployment):
        """RLS: User B cannot see User A data."""
```

**NFR-S4 Verification Script:**
```bash
# Verify no voiceprint or biometric data anywhere
# Check database schemas
psql -h localhost -p 5432 -U lis -d lis -c \
  "SELECT column_name FROM information_schema.columns WHERE
   column_name ILIKE '%voiceprint%' OR
   column_name ILIKE '%biometric%' OR
   column_name ILIKE '%speaker_embedding%' OR
   column_name ILIKE '%voice_print%';"
# Expected: 0 rows

# Check MinIO for biometric files
mc ls minio/lis-data/ --recursive | grep -iE 'voiceprint|biometric|speaker_embedding'
# Expected: no results

# Check git history
git log --all --oneline | grep -iE 'voiceprint|biometric'
# Expected: no results (except possibly ADR discussing the decision)
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `TRIVY_SEVERITY` | string | Trivy severity filter | `CRITICAL,HIGH` |
| `GRYPE_FAIL_ON` | string | Grype fail threshold | `critical` |
| `SEMGREP_CONFIG` | string | Semgrep config | `auto` |
| `GITLEAKS_REPORT_PATH` | string | gitleaks report output | `gitleaks-report.json` |
| `SBOM_OUTPUT_DIR` | string | SBOM output directory | `sbom/` |
| `LICENCE_REGISTER_PATH` | string | §30 licence register | `docs/licence-register.md` |
| `ZAP_TARGET_URL` | string | OWASP ZAP target | `http://localhost:8000` |
| `ZAP_API_KEY` | string | ZAP API key | `changeme-...` |
| `LEGAL_SIGNOFF_DIR` | string | Legal sign-off documents | `docs/legal/signoffs/` |
| `ACCEPTANCE_TEST_DEPLOYMENT` | string | Deployment URL for AC tests | `http://localhost:8000` |

**Docker Compose Services Required:**
- Full production deployment (all services running)
- Trivy/Grype (or installed on CI runner)
- Semgrep/Bandit (or installed on CI runner)
- OWASP ZAP (for penetration testing)
- Locust (for load testing)

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Given | When | Then |
|---------|------|-------|------|------|
| T76.1 | E | Full deployment running with all services | Execute AC-1 through AC-20 test suite | All 20 acceptance criteria tests pass against full deployment |
| T76.2 | S | All shipped container images identified | Trivy + Grype scan on each image | No critical or high CVEs unresolved in any shipped image |
| T76.3 | S | Full codebase available | Semgrep + Bandit SAST scan | SAST clean; FR-4.9 Semgrep boundary rule present and passing (S63 T63.3 regression) |
| T76.4 | S | pip-licenses + syft output; §30 licence register | Licence audit against register | Licence audit clean; every flagged component resolved or consciously accepted with recorded decision |
| T76.5 | S | All shipped container images | syft SBOM generation | SBOM generated and stored per image in SPDX format |
| T76.6 | S | Full git history | gitleaks detect | No secrets found in git history |
| T76.7 | S | Full system database and storage | NFR-S4 verification scan | No voiceprint or biometric data anywhere in the system (S20 T20.2 regression) |
| T76.8 | M | Recording consent templates (D-11); data privacy requirements | Legal review of consent and recording legality | Legal review documented and signed off by qualified legal counsel |
| T76.9 | S | API surface deployed | OWASP ZAP penetration test of API | Penetration test completed; all findings triaged (critical/high fixed, medium/low documented) |
| T76.10 | M | Backup/restore infrastructure from S71 | Re-execute restore drill post-hardening | Restore drill passes successfully; backup integrity confirmed |

**Verification Commands:**
```bash
# Run all 20 AC tests
uv run pytest tests/acceptance/test_ac_suite.py -v --tb=short

# Run regression tests
uv run pytest tests/acceptance/test_regression_suite.py -v --tb=short

# Trivy scan
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-api:latest
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-worker:latest
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-asr:latest
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-llm:latest

# Grype scan (cross-validation)
grype lis-api:latest --fail-on critical
grype lis-worker:latest --fail-on critical

# Semgrep SAST
semgrep scan --config auto --severity ERROR src/

# Bandit SAST
bandit -r src/ -ll --format json --output bandit-report.json

# gitleaks
gitleaks detect --source . --report-format json --report-path gitleaks-report.json

# SBOM generation
mkdir -p sbom
syft lis-api:latest -o spdx-json=sbom/lis-api-sbom.json
syft lis-worker:latest -o spdx-json=sbom/lis-worker-sbom.json
syft lis-asr:latest -o spdx-json=sbom/lis-asr-sbom.json
syft lis-llm:latest -o spdx-json=sbom/lis-llm-sbom.json

# Licence audit
pip-licenses --format=json --output-file licences/pip-licenses.json
python scripts/licence/audit_licence_register.py --register docs/licence-register.json

# NFR-S4 verification
python scripts/security/verify_no_biometric.py

# Penetration test
zap-full-scan.py -t http://localhost:8000 -r zap-report.html

# Restore drill re-execution
bash scripts/restore/drill.sh

# Full gate verification
echo "=== G7 GATE VERIFICATION ==="
uv run pytest tests/acceptance/test_ac_suite.py -v --tb=short && \
uv run pytest tests/acceptance/test_regression_suite.py -v --tb=short && \
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-api:latest && \
trivy image --severity CRITICAL,HIGH --exit-code 1 lis-worker:latest && \
semgrep scan --config auto --severity ERROR src/ && \
bandit -r src/ -ll && \
gitleaks detect --source . && \
python scripts/security/verify_no_biometric.py && \
bash scripts/restore/drill.sh && \
echo "=== G7 GATE PASSED ==="
```

**Exit Criteria:**
- [ ] **AC-1 through AC-20 all pass** (T76.1)
- [ ] No critical or high CVEs unresolved (T76.2)
- [ ] SAST clean; FR-4.9 boundary rule present (T76.3)
- [ ] Licence audit clean against §30 register (T76.4)
- [ ] SBOM generated per image (T76.5)
- [ ] No secrets in git history (T76.6)
- [ ] No voiceprint/biometric data anywhere (T76.7)
- [ ] Legal sign-off recorded (T76.8)
- [ ] Penetration test findings triaged (T76.9)
- [ ] Restore drill re-executed successfully (T76.10)

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- Trivy and Grype may report different CVEs; reconcile differences manually
- Semgrep may produce false positives on legitimate code; suppress with `nosemgrep` comments (documented)
- pip-licenses may miss dependencies in virtual environments; ensure full environment scanned
- AC tests may be flaky due to timing; use generous timeouts and retries
- Legal sign-off may take weeks; start early
- Penetration test findings may require code changes; budget time for remediation
- Restore drill may fail if infrastructure changed since S71; re-verify infrastructure

**Fallback Instructions:**
- If critical CVE found, upgrade dependency and re-scan
- If AC test fails, investigate root cause; may need code fix or test fix
- If licence audit fails, get legal decision or replace component
- If penetration test finds critical, fix immediately and re-test
- If restore drill fails, fix backup/restore and re-execute

**Rollback Procedure:**
- Security: fix findings; no rollback needed (this is an audit stage)
- AC tests: fix system or test; no rollback needed
- Licence: replace unapproved component or get legal acceptance
- Legal: no rollback; must get sign-off before release
- This stage is a gate, not a deployment; rollback means "don't release"

---

### 9. Observability (if applicable)

**Metrics Added:**
- `lis_acceptance_ac_test_total{ac_id, status}`: Counter of AC test results
- `lis_acceptance_regression_test_total{test_id, status}`: Counter of regression test results
- `lis_security_scan_critical_total{scan_type, image}`: Counter of critical findings
- `lis_security_scan_high_total{scan_type, image}`: Counter of high findings
- `lis_licence_audit_flagged_total`: Counter of flagged licence components
- `lis_licence_audit_approved_total`: Counter of approved licence components
- `lis_penetration_test_findings_total{severity}`: Counter of pen test findings
- `lis_restore_drill_success_total`: Counter of successful restore drills

**Tracing/Logging:**
- Span: `gate.ac_test_suite` for full AC test execution
- Span: `gate.security_scan` for security scanning phase
- Span: `gate.licence_audit` for licence audit phase
- Span: `gate.restore_drill` for restore drill re-execution
- Log event: `gate_ac_test_completed` with ac_id, status, duration
- Log event: `gate_security_scan_completed` with scan_type, critical, high, medium, low
- Log event: `gate_licence_audit_completed` with flagged, approved, denied
- Log event: `gate_restore_drill_completed` with status, duration
- Log event: `gate_legal_signoff_received` with signoff_type, signed_by
- Log event: `gate_final_decision` with decision (passed/failed), criteria_met

**Alerts:**
- Alert if any AC test fails
- Alert if critical CVE found
- Alert if licence audit fails
- Alert if restore drill fails
- Alert if legal sign-off not received within deadline

---

### 10. Exit Checklist

- [ ] **All 20 AC tests pass** (T76.1) — **HARD GATE**
- [ ] No critical or high CVEs unresolved (T76.2)
- [ ] SAST clean; FR-4.9 boundary rule present (T76.3)
- [ ] Licence audit clean against §30 register (T76.4)
- [ ] SBOM generated per image (T76.5)
- [ ] No secrets in git history (T76.6)
- [ ] No voiceprint/biometric data anywhere (T76.7)
- [ ] Legal sign-off recorded (T76.8)
- [ ] Penetration test findings triaged (T76.9)
- [ ] Restore drill re-executed successfully (T76.10)
- [ ] Security report complete
- [ ] Licence audit report complete
- [ ] Legal review documented
- [ ] SBOM stored per image
- [ ] **SYSTEM IS RELEASABLE**
