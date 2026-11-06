-- GitHub tokens the CTO adds on a screen (FR-INTG-21, ADR-0076). Encrypted like the AI keys; names keep the GITHUB_TOKEN_* shape
-- so a project's credential_ref points at either one of these rows or an environment variable of the same name.
CREATE TABLE IF NOT EXISTS github_tokens (
    name VARCHAR(64) PRIMARY KEY,
    token_enc TEXT NOT NULL,
    key_hint VARCHAR(8) NOT NULL DEFAULT '',
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
