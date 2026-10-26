-- Shared retention boundary. Import/export writers must consult these floors.
CREATE TABLE operations_retention_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    request_floor timestamptz NOT NULL,
    projection_floor timestamptz NOT NULL,
    outbox_floor timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

-- Participants release their holds in the same transaction as terminal/pruned work.
-- No automatic expiry: age alone does not prove that dependent work is finished.
CREATE TABLE operations_retention_hold (
    participant text NOT NULL CHECK (participant IN ('gateway', 'projection', 'outbox')),
    reference text NOT NULL,
    request_id uuid NOT NULL REFERENCES lineage_ingress(request_id),
    PRIMARY KEY (participant, reference, request_id)
);
CREATE INDEX operations_hold_request ON operations_retention_hold(request_id);
CREATE INDEX operations_ingress_time ON lineage_ingress(accepted_at);
CREATE INDEX operations_event_time ON lineage_usage_event(first_seen_at);
