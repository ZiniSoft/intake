-- Speech-to-text becomes a routable task (FR-AI-20, ADR-0075): meeting recordings can use any provider the CTO connects.
ALTER TABLE ai_routes DROP CONSTRAINT IF EXISTS ck_ai_routes_task;
ALTER TABLE ai_routes ADD CONSTRAINT ck_ai_routes_task CHECK (task IN ('default', 'normalize', 'report', 'meeting', 'vision', 'content', 'stt'));
