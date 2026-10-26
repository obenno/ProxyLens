-- External group references only: Keycloak remains the identity authority.
CREATE TABLE resource_group_refs (
    id text PRIMARY KEY,
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'orphaned')),
    verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    policy jsonb NOT NULL DEFAULT '{}',
    policy_version bigint NOT NULL DEFAULT 0
);

CREATE TABLE resource_applications (
    id uuid PRIMARY KEY,
    group_id text NOT NULL REFERENCES resource_group_refs(id),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    state text NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'disabled', 'orphaned', 'revoked')),
    policy jsonb NOT NULL DEFAULT '{}',
    policy_version bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    predecessor_id uuid REFERENCES resource_applications(id),
    UNIQUE (id, group_id)
);

CREATE TABLE resource_client_keys (
    id uuid PRIMARY KEY,
    application_id uuid NOT NULL,
    group_id text NOT NULL,
    prefix text NOT NULL UNIQUE,
    secret_hash text NOT NULL UNIQUE CHECK (secret_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz,
    revoked_at timestamptz,
    FOREIGN KEY (application_id, group_id) REFERENCES resource_applications(id, group_id)
);
CREATE INDEX resource_keys_application ON resource_client_keys(application_id);
CREATE INDEX resource_applications_group ON resource_applications(group_id);

CREATE TABLE resource_audit (
    id uuid PRIMARY KEY,
    actor text,
    group_id text,
    resource_id text,
    action text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    outcome text NOT NULL CHECK (outcome IN ('success', 'denied')),
    details jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX resource_audit_group_time ON resource_audit(group_id, occurred_at DESC);

CREATE TABLE resource_rate_windows (
    scope text NOT NULL,
    window_start timestamptz NOT NULL,
    count bigint NOT NULL CHECK (count > 0),
    PRIMARY KEY (scope, window_start)
);
