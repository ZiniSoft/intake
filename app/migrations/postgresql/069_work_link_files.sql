-- A link on a work item can be a file from the computer: a picture or a PDF kept in object storage (FR-WRK-10).
ALTER TABLE work_links ADD COLUMN IF NOT EXISTS object_key VARCHAR(200);
ALTER TABLE work_links ADD COLUMN IF NOT EXISTS file_name VARCHAR(255);
ALTER TABLE work_links ADD COLUMN IF NOT EXISTS mime_type VARCHAR(100);
ALTER TABLE work_links ADD COLUMN IF NOT EXISTS size_bytes INTEGER;
