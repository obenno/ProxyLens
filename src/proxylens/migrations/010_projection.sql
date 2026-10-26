-- Rebuildable CPAMP projection, never a ledger or cached authorization decision.
CREATE TABLE IF NOT EXISTS projection_sources (
    cpamp_instance_id text PRIMARY KEY,
    cpa_instance_id text NOT NULL,
    binding jsonb NOT NULL,
    last_success_ms bigint,
    last_attempt_ms bigint,
    last_reconcile_ms bigint,
    window_from_ms bigint,
    window_to_ms bigint,
    coverage jsonb NOT NULL DEFAULT '[]',
    reasons jsonb NOT NULL DEFAULT '[]',
    failed boolean NOT NULL DEFAULT false,
    duplicate_count bigint NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projection_records (
    cpamp_instance_id text NOT NULL REFERENCES projection_sources(cpamp_instance_id),
    event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
    timestamp_ms bigint NOT NULL,
    facts jsonb NOT NULL,
    PRIMARY KEY (cpamp_instance_id, event_hash),
    FOREIGN KEY (cpamp_instance_id, event_hash)
        REFERENCES lineage_usage_event(cpamp_instance_id, event_hash)
);
CREATE INDEX IF NOT EXISTS projection_records_time
    ON projection_records(cpamp_instance_id, timestamp_ms DESC, event_hash);

-- Crash leftovers are isolated from readers; next locked run discards them.
CREATE TABLE IF NOT EXISTS projection_runs (
    run_id uuid PRIMARY KEY,
    cpamp_instance_id text NOT NULL REFERENCES projection_sources(cpamp_instance_id),
    from_ms bigint NOT NULL,
    to_ms bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS projection_stage (
    run_id uuid NOT NULL REFERENCES projection_runs(run_id) ON DELETE CASCADE,
    event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
    timestamp_ms bigint NOT NULL,
    facts jsonb NOT NULL,
    PRIMARY KEY (run_id, event_hash)
);

-- Every read must use this dynamic resolution, including exporter enrichment.
CREATE OR REPLACE VIEW projection_resolved AS
SELECT p.cpamp_instance_id, p.event_hash, p.timestamp_ms, p.facts,
       r.cpa_instance_id, r.cpa_request_id, r.correlation_status, r.request_id,
       i.keycloak_issuer, i.keycloak_group_id AS group_id, i.application_id,
       i.client_key_id, i.subject, i.trace_id, i.generation_id, i.session_id
FROM projection_records p
JOIN lineage_event_resolution r USING (cpamp_instance_id, event_hash)
LEFT JOIN lineage_ingress i ON i.request_id = r.request_id;
