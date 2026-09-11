# Claims Fraud Flagging Dashboard

Real-time fraud risk scoring for insurance claims, built for TECHNOVATE Hackathon 2026 (Problem Statement 6).

Claims stream through a Kafka pipeline, get scored by a rule-based engine with simple pattern detection, and surface on a live dashboard with the reasons behind every flag.

## Live Demo

**[simple-orchestra-website-organizations.trycloudflare.com](https://simple-orchestra-website-organizations.trycloudflare.com/)**

⚠️ **Temporary link, not a permanent deployment.** The full pipeline (Kafka, MySQL, the consumer, and the dashboard) runs on a team member's own machine — this URL is a [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) exposing it publicly. It only works while that machine is on and the tunnel process is running, and a new tunnel gets a **different** random URL — so if this link is dead, it means the demo isn't currently running, not that the project is broken. See [`docs/deployment.md`](docs/deployment.md) for how this is set up and how to run it yourself.

If this link has gone dead, whoever's running the demo can bring up a fresh one with:
```
cloudflared tunnel --url http://localhost:8501 2>&1 | tee cloudflared.log | grep --line-buffered -o 'https://[A-Za-z0-9.-]*trycloudflare\.com'
```

---

## Problem

Insurers lose significant revenue to fraudulent and inflated claims. Manual review is too slow to catch patterns across large claim volumes — by the time a reviewer spots a repeat claimant or a colluding provider, the payouts have already gone out.

## Approach

Every incoming claim is scored 0–100 by two complementary layers:

**Rule-based checks** — evaluated on the claim alone
- Claim amount far above the average for its category
- Claim filed shortly after policy start date
- Round-number claim amounts
- Claim submitted at unusual hours
- Claimant address far from incident or provider location

**Pattern detection** — evaluated against claim history
- Multiple claims from the same claimant within a rolling window
- One provider recurring across many unrelated claimants
- Claim frequency spike against a policyholder's own baseline

Claims crossing the risk threshold are written to a separate alerts table with the list of triggered checks attached, so every flag is explainable.

See [`docs/consumer-rule-pattern-engine.md`](docs/consumer-rule-pattern-engine.md) for the exact thresholds, weights, the research behind the design, and how the weights were calibrated against measured false-positive rates.

## Case Management

A flagged claim becomes a case that moves through a status lifecycle rather than sitting as a static "flagged" record:

`pending_review` → `under_investigation` → `escalated` → `cleared` / `confirmed_fraud`

- **Assignment** — cases are assigned to an investigator (no login/auth in this build — investigators are a simple name list, not user accounts)
- **Notes** — investigators log timestamped notes and findings against a case
- **Audit trail** — every status, assignment, and resolution change is logged automatically by a database trigger, independent of which app code made the change
- **Entity tracking** — `claimants` and `providers` are tracked as running aggregates (claim count, flagged count, avg/max risk score; providers also track distinct-claimant reach), kept in sync by triggers on every incoming claim, so a repeat offender is visible immediately without an ad-hoc query

See `db/mysql-init.sql` for the full schema and trigger definitions, or
[`docs/schema-erd.html`](docs/schema-erd.html) for a crow's-foot ER diagram of every
table, column, PK/FK, and cardinality (open it in a browser).

---

## Architecture

```
Layer 1  R generator (SynthETIC + fraud archetypes)  →  claims_data.csv
Layer 2  producer.py  →  Kafka topic: claims-stream
Layer 3  consumer.py  →  rule checks + pattern detection  →  risk score
Layer 4  MySQL/Postgres  →  claims, fraud_alerts, claimants/providers, case_notes, audit_log
Layer 5  Streamlit dashboard  →  live feed, metrics, alerts panel
```

Layers 2–5 run in Docker Compose. Layer 1 runs once, offline, and is not part of the running system.

## Tech Stack

| Layer | Technology |
|---|---|
| Data generation | R, SynthETIC |
| Streaming | Apache Kafka, Zookeeper, kafka-python |
| Processing | Python (rule engine + pattern detection) |
| Storage | MySQL 8, containerized via Docker Compose |
| Dashboard | Streamlit (Grafana as fallback) |
| Orchestration | Docker Compose |

---

## Repository Structure

```
├── data-gen/          R script and fraud archetype injection
├── producer/          Kafka producer, replays claims_data.csv
├── consumer/          Scoring engine — rules and pattern modules
├── db/                Schema definitions
├── dashboard/         Streamlit app
├── docs/              Setup instructions, design docs, PPT assets
└── docker-compose.yml
```

## Getting Started

Setup steps, prerequisites, and run order are in [INSTRUCTIONS.md](INSTRUCTIONS.md).

---

## Why the data is synthetic

Fraud labels are inherently retrospective — a claim is only confirmed fraudulent after investigation, days or weeks later. No live fraud-labeled feed exists anywhere, including inside real insurers. The standard approach in fraud-detection research is to stream a prepared dataset through the pipeline, which is exactly what this project does: the data is generated once with realistic actuarial distributions, then replayed in real time so the pipeline processes each claim as it arrives.

## Scope

Deliberately limited to rule-based checks and simple pattern detection, per the problem statement. Machine learning is out of scope for this build and is documented as future work.

## Team

Six contributors, one per layer plus integration. See repository contributors.
