-- Immutable authorization snapshot, not authoritative application/key/group models.
CREATE TABLE IF NOT EXISTS lineage_ingress (
    request_id uuid PRIMARY KEY,
    keycloak_issuer text NOT NULL,
    keycloak_group_id text NOT NULL,
    application_id text NOT NULL,
    client_key_id text NOT NULL,
    subject text,
    accepted_at timestamptz NOT NULL,
    trace_id text NOT NULL UNIQUE CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    generation_id text NOT NULL CHECK (generation_id ~ '^[0-9a-f]{16}$'),
    session_id text NOT NULL
);

-- Multiple ingress claims are retained to expose, not conceal, a native collision.
CREATE TABLE IF NOT EXISTS lineage_native_binding (
    cpa_instance_id text NOT NULL,
    cpa_request_id uuid NOT NULL,
    request_id uuid NOT NULL REFERENCES lineage_ingress(request_id),
    bound_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cpa_instance_id, cpa_request_id, request_id)
);

CREATE TABLE IF NOT EXISTS lineage_usage_event (
    cpamp_instance_id text NOT NULL,
    event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
    cpa_instance_id text NOT NULL,
    cpa_request_id uuid,
    conflicted boolean NOT NULL DEFAULT false,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cpamp_instance_id, event_hash)
);
CREATE INDEX IF NOT EXISTS lineage_usage_native_idx
    ON lineage_usage_event (cpa_instance_id, cpa_request_id);

-- Always resolve at read time: later collisions invalidate EARLIER event ownership.
-- Consumers must not publish cached owner columns after this relation changes.
CREATE OR REPLACE VIEW lineage_event_resolution AS
SELECT e.cpamp_instance_id, e.event_hash, e.cpa_instance_id, e.cpa_request_id,
       CASE WHEN e.conflicted OR matches.claims > 1 THEN 'ambiguous'
            WHEN e.cpa_request_id IS NULL THEN 'missing'
            WHEN matches.claims = 0 THEN 'partial'
            ELSE 'correlated' END AS correlation_status,
       CASE WHEN NOT e.conflicted AND matches.claims = 1
            THEN matches.request_id END AS request_id
FROM lineage_usage_event e
CROSS JOIN LATERAL (
    SELECT count(*) AS claims, min(b.request_id::text)::uuid AS request_id
    FROM lineage_native_binding b
    WHERE b.cpa_instance_id = e.cpa_instance_id AND b.cpa_request_id = e.cpa_request_id
) matches;
