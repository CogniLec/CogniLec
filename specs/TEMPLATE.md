# S## — Stage Name
## Specification Document

---

### 1. Context & Execution Scope

**Goal:** [Single-sentence explanation of what this stage builds]

**Component Boundaries:**
- **Allowed:** [Files/directories the agent is allowed to touch]
- **Off-limits:** [Files/directories strictly off-limits]

**Tech Stack & Version Pinning:**
| Tool | Version | Purpose |
|------|---------|---------|
| [Tool] | [Version] | [Purpose] |

---

### 2. State Machine & Domain Schemas

**[State/Domain Name]:**
```
[State transitions or domain schemas]
```

**[Pydantic/SQLAlchemy/TypeScript] Models:**
```python
[Code examples with exact types and schemas]
```

**State Transition Rules:**
- [Rule 1: Input → Output state with conditions]
- [Rule 2: Input → Output state with conditions]

---

### 3. Step-by-Step Execution Protocol

| Step | Action | Verification |
|------|--------|--------------|
| 1 | [Action] | [Verification command/output] |
| 2 | [Action] | [Verification command/output] |

**Atomic Sub-tasks:**
1. [Sub-task 1]
2. [Sub-task 2]

**Edge Case Matrix:**
| Error | Handling |
|-------|----------|
| [Error condition] | [Handling strategy] |

---

### 4. Code Style & Architecture Constraints

**Design Patterns:**
- [Pattern 1: e.g., Repository Pattern]
- [Pattern 2: e.g., Dependency Injection]

**Naming & Style Guidelines:**
- Variables: [naming convention]
- Classes: [naming convention]
- Files: [naming convention]
- Functions: [naming convention]

**Code Splitting Metrics:**
- Max function length: [lines]
- Max file length: [lines]
- [Other constraints]

**Type Safety:**
- [Type hints requirements]
- [Strict mode settings]

---

### 5. API & Interface Contracts

**[API/Service] Endpoints:**
```yaml
[OpenAPI/Protocol Buffer specs]
```

**Mock Request/Response Payloads:**
```json
[Request payload]
```
```json
[Response payload]
```

**Database Schema (if applicable):**
```sql
[DDL statements]
```

**Event/Message Contracts:**
```json
[Event schema]
```

---

### 6. Dependency & Environment Configuration

**Required `.env` Variables:**
| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| [VAR] | [type] | [description] | [example] |

**Third-Party Integration Contracts:**
- [Service 1]: [SDK expectations, stubbed definitions]
- [Service 2]: [SDK expectations, stubbed definitions]

**Version Pins:**
- [Critical version pins enforced by CI]

---

### 7. Definition of Done & Verification

**Automated Test Matrix:**
| Test ID | Type | Command | Expected |
|---------|------|---------|----------|
| T##.1 | [U/I/E/V/M/S/P] | [command] | [expected result] |
| T##.2 | [U/I/E/V/M/S/P] | [command] | [expected result] |

**Verification Commands:**
```bash
# Full local verification
[verification script]
```

**Exit Criteria:**
- [ ] [Criterion 1]
- [ ] [Criterion 2]

---

### 8. Failure Modes & Self-Correction

**Known Gotchas:**
- [Gotcha 1: Common anti-pattern or quirk]
- [Gotcha 2: Common anti-pattern or quirk]

**Fallback Instructions:**
- If [condition], then [action]
- If [condition], then [action]

**Rollback Procedure:**
- [How to revert changes]
- [Migration down-path]
- [Feature flag to disable]

---

### 9. Observability (if applicable)

**Metrics Added:**
- [Metric 1]: [description]
- [Metric 2]: [description]

**Tracing/Logging:**
- [Trace spans added]
- [Log events added]

**Alerts:**
- [Alert 1]: [condition and action]

---

### 10. Exit Checklist

- [ ] All tests pass (T##.1, T##.2, ...)
- [ ] [Specific gate criteria if applicable]
- [ ] [Other exit conditions from implementation plan]
