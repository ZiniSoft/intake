-- Who made the acceptance final (ADR-0082): CTO, or the Project Owner when the project lets them close low-risk work.
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS final_by VARCHAR(16);
