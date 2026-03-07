-- Add sources_document_metadata_json column to search_queries
-- Run this if you have an existing database before the model change.

-- SQLite
ALTER TABLE search_queries ADD COLUMN sources_document_metadata_json TEXT;

-- MySQL (if using MySQL instead)
-- ALTER TABLE search_queries ADD COLUMN sources_document_metadata_json JSON NULL;
