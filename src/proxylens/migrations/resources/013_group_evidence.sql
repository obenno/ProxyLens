-- Nested groups are authoritative but unsupported for resource ownership.
-- Preserve them as unusable instead of collapsing them into an outage.
ALTER TABLE resource_group_refs
    DROP CONSTRAINT IF EXISTS resource_group_refs_state_check;
ALTER TABLE resource_group_refs
    ADD CONSTRAINT resource_group_refs_state_check
    CHECK (state IN ('active', 'orphaned', 'unusable'));

ALTER TABLE resource_applications
    DROP CONSTRAINT IF EXISTS resource_applications_state_check;
ALTER TABLE resource_applications
    ADD CONSTRAINT resource_applications_state_check
    CHECK (state IN ('active', 'disabled', 'orphaned', 'unusable', 'revoked'));
