-- Whether a provider's model passed a sample picture or a sample sound (FR-AI-21, ADR-0077). A model that failed the picture
-- check is not used for reading attachments through the default route; an unchecked one still is.
CREATE TABLE IF NOT EXISTS ai_model_checks (
    provider_id UUID NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
    model VARCHAR(128) NOT NULL,
    kind VARCHAR(16) NOT NULL CONSTRAINT ck_ai_model_checks_kind CHECK (kind IN ('vision', 'stt')),
    ok BOOLEAN NOT NULL,
    error VARCHAR(32),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider_id, model, kind)
);
