-- Add feedback columns to search_queries (Option 1: lightweight fields)
-- Run this if you have an existing database before the model change.

-- SQLite
ALTER TABLE search_queries ADD COLUMN feedback_status VARCHAR(16);
ALTER TABLE search_queries ADD COLUMN feedback_score INTEGER;
ALTER TABLE search_queries ADD COLUMN feedback_reason VARCHAR(64);
ALTER TABLE search_queries ADD COLUMN feedback_text TEXT;
ALTER TABLE search_queries ADD COLUMN feedback_at TIMESTAMP;

-- MySQL (if using MySQL instead)
-- ALTER TABLE search_queries ADD COLUMN feedback_status VARCHAR(16) NULL;
-- ALTER TABLE search_queries ADD COLUMN feedback_score INT NULL;
-- ALTER TABLE search_queries ADD COLUMN feedback_reason VARCHAR(64) NULL;
-- ALTER TABLE search_queries ADD COLUMN feedback_text TEXT NULL;
-- ALTER TABLE search_queries ADD COLUMN feedback_at DATETIME NULL;
