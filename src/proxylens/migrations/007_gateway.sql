-- Transport lifecycle only; model content and upstream error bodies are never stored.
CREATE TABLE gateway_lifecycle (
    request_id uuid PRIMARY KEY REFERENCES lineage_ingress(request_id),
    requested_model text NOT NULL,
    routing_model text NOT NULL,
    routing_provider text NOT NULL,
    group_policy_version bigint NOT NULL,
    application_policy_version bigint NOT NULL,
    dispatch_intent_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    headers_at timestamptz,
    first_byte_at timestamptz,
    completed_at timestamptz,
    http_status integer CHECK (http_status BETWEEN 100 AND 599),
    duration_ms bigint CHECK (duration_ms >= 0),
    response_bytes bigint NOT NULL DEFAULT 0 CHECK (response_bytes >= 0),
    outcome text NOT NULL DEFAULT 'pending' CHECK (outcome IN
        ('pending', 'completed', 'upstream_error', 'timeout', 'cancelled',
         'transport_error', 'storage_error', 'internal_error'))
);
CREATE INDEX gateway_completion_idx ON gateway_lifecycle(completed_at, request_id);

-- Exporters join this metadata to immutable ownership/observation IDs. Native
-- bindings must be checked at read time for collisions; never infer usage here.
CREATE VIEW gateway_observations AS
SELECT i.*, g.requested_model, g.routing_model, g.routing_provider,
       g.group_policy_version, g.application_policy_version, g.dispatch_intent_at,
       g.headers_at, g.first_byte_at, g.completed_at, g.http_status, g.duration_ms,
       g.response_bytes, g.outcome
FROM lineage_ingress i JOIN gateway_lifecycle g USING (request_id);
