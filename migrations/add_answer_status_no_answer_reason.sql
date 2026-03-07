-- Add answer_status and no_answer_reason columns to search_queries
-- Run this if you have an existing database before the model change.

-- SQLite
ALTER TABLE search_queries ADD COLUMN answer_status VARCHAR(32);
ALTER TABLE search_queries ADD COLUMN no_answer_reason VARCHAR(32);

-- MySQL (if using MySQL instead)
-- ALTER TABLE search_queries ADD COLUMN answer_status VARCHAR(32) NULL;
-- ALTER TABLE search_queries ADD COLUMN no_answer_reason VARCHAR(32) NULL;
