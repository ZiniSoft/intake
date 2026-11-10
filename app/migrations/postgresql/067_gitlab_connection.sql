-- The company GitLab the CTO connects on a screen (FR-INTG-22, ADR-0080): one row, token encrypted like the GitHub
-- tokens (ADR-0076). GITLAB_BASE_URL / GITLAB_TOKEN in .env stay as the fallback when this row is absent.
CREATE TABLE IF NOT EXISTS gitlab_connection (
    id VARCHAR(16) PRIMARY KEY,
    base_url VARCHAR(255) NOT NULL,
    token_enc TEXT NOT NULL,
    key_hint VARCHAR(8) NOT NULL DEFAULT '',
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_gitlab_connection_single CHECK (id = 'default')
);

-- ACCESS: the integration worker reports which permissions a token has and which are missing (FR-INTG-23).
ALTER TABLE integration_probes DROP CONSTRAINT IF EXISTS integration_probes_action_check;
ALTER TABLE integration_probes DROP CONSTRAINT IF EXISTS ck_integration_probe_action;
ALTER TABLE integration_probes
    ADD CONSTRAINT ck_integration_probe_action CHECK (action IN ('LIST', 'CHECK', 'MEMBERS', 'TOKENS', 'ACCESS'));
