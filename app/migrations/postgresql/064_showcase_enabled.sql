-- Showcase catalogue (FR-SETUP-15): which catalogue items the CTO switched on and the project each one created.
CREATE TABLE IF NOT EXISTS showcase_enabled (
    item_key VARCHAR(64) PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    catalog_version INTEGER NOT NULL,
    enabled_by UUID REFERENCES users(id),
    enabled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
