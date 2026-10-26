-- Runtime tables are placed after resources/009 so all referenced tables exist
-- on a fresh Database.migrate() run. The runtime also depends on root 003/007/008/010.
CREATE TABLE operations_scan (
    destination text NOT NULL,
    request_id uuid NOT NULL REFERENCES lineage_ingress(request_id) ON DELETE CASCADE,
    scanned_at timestamptz NOT NULL,
    code text NOT NULL,
    PRIMARY KEY (destination, request_id)
);
CREATE TABLE operations_status (
    component text PRIMARY KEY,
    observed_at timestamptz NOT NULL,
    state text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'
);
