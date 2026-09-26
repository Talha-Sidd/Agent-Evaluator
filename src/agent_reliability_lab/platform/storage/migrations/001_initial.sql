CREATE TABLE stored_runs (
    run_id uuid PRIMARY KEY,
    owner text NOT NULL,
    scenario_id text NOT NULL,
    result_json jsonb NOT NULL,
    evaluation_json jsonb NOT NULL,
    agent_version text NOT NULL,
    evaluator_version text NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    size_bytes integer NOT NULL CHECK (size_bytes > 0)
);
CREATE INDEX stored_runs_retention_idx ON stored_runs (created_at, run_id);
CREATE INDEX stored_runs_owner_idx ON stored_runs (owner, run_id);
CREATE INDEX stored_runs_expiry_idx ON stored_runs (expires_at);
CREATE TABLE stored_trace_events (
    event_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES stored_runs (run_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    event_json jsonb NOT NULL,
    UNIQUE (run_id, ordinal)
);
