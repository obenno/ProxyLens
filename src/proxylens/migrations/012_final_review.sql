ALTER TABLE exporter_outbox
    ADD COLUMN source_cpamp_instance_id text,
    ADD COLUMN source_event_hash text,
    ADD COLUMN source_cpa_instance_id text,
    ADD COLUMN source_keycloak_issuer text;

CREATE INDEX exporter_source_lineage
    ON exporter_outbox(
        destination,
        source_cpamp_instance_id,
        source_event_hash,
        source_cpa_instance_id,
        source_keycloak_issuer
    )
    WHERE source_event_hash IS NOT NULL;
