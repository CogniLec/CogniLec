-- S39 -- agent_runs: queryable system of record for LLM invocation
-- tracing and cost. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(10) NOT NULL,
    model VARCHAR(100) NOT NULL,
    tier VARCHAR(20) NOT NULL,
    prompt_version VARCHAR(50) NOT NULL,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    cost_usd DECIMAL(10, 6) DEFAULT 0.0,
    latency_ms INT DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_trace ON agent_runs (trace_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs (agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_tier ON agent_runs (tier);
