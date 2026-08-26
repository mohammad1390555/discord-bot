-- Add ticket enhancements: priority, rating, transcript storage, close reason.
ALTER TABLE tickets ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium';
ALTER TABLE tickets ADD COLUMN closed_by INTEGER;
ALTER TABLE tickets ADD COLUMN close_reason TEXT;
ALTER TABLE tickets ADD COLUMN rating INTEGER;
