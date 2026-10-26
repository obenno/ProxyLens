-- Independent outbox; source lifecycle adapters are wired by operations integration.
CREATE TABLE exporter_outbox (
    destination text NOT NULL,
    request_id uuid NOT NULL,
    trace_id text NOT NULL,
    generation_id text NOT NULL,
    identity_hash text NOT NULL,
    started_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    finalize_after timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    state text NOT NULL CHECK (state IN (
        'WAITING', 'READY', 'IN_FLIGHT', 'RETRY_WAIT', 'ACCEPTED', 'UNCERTAIN', 'DEAD_LETTER'
    )),
    payload bytea NOT NULL,
    payload_hash text NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at timestamptz NOT NULL,
    first_attempt_at timestamptz,
    lease_token uuid,
    lease_until timestamptz,
    last_code text,
    remote_snapshot_stale boolean NOT NULL DEFAULT false,
    late_payload_hash text,
    PRIMARY KEY (destination, request_id),
    UNIQUE (destination, trace_id),
    UNIQUE (destination, generation_id),
    CHECK ((state = 'IN_FLIGHT') = (lease_token IS NOT NULL AND lease_until IS NOT NULL)),
    CHECK (length(trace_id) = 32 AND length(generation_id) = 16)
);
CREATE INDEX exporter_due ON exporter_outbox(destination, state, next_attempt_at);
CREATE TABLE exporter_counters (
    destination text NOT NULL,
    code text NOT NULL,
    count bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (destination, code)
);
