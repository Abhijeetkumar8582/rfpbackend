-- Consolidated migration: rename ts -> datetime, drop project_id, add conversation_id.
-- Use this if your search_queries table still has columns ts and project_id.
-- Run in order below (MySQL 8.0.3+). For PostgreSQL, uncomment the PG blocks.

-- ========== 1. Rename ts to datetime, drop project_id ==========
-- MySQL: drop FK before dropping the column.

-- MySQL:
ALTER TABLE search_queries RENAME COLUMN ts TO datetime;
ALTER TABLE search_queries DROP FOREIGN KEY fk_search_queries_project_id;
ALTER TABLE search_queries DROP COLUMN project_id;

-- PostgreSQL:
-- ALTER TABLE search_queries RENAME COLUMN ts TO datetime;
-- ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS search_queries_project_id_fkey;
-- ALTER TABLE search_queries DROP COLUMN project_id;

-- ========== 2. Add conversation_id (VARCHAR(32) NOT NULL) ==========

-- MySQL:
ALTER TABLE search_queries
  ADD COLUMN conversation_id VARCHAR(32) NOT NULL DEFAULT 'conv_LEGACY0000000000000000'
  AFTER datetime;

-- PostgreSQL:
-- ALTER TABLE search_queries ADD COLUMN conversation_id VARCHAR(32);
-- UPDATE search_queries SET conversation_id = 'conv_LEGACY' || LPAD(id::text, 26, '0') WHERE conversation_id IS NULL;
-- ALTER TABLE search_queries ALTER COLUMN conversation_id SET NOT NULL;

-- Optional: backfill existing rows with unique conv_<ULID> via app, then drop default (MySQL):
-- ALTER TABLE search_queries ALTER COLUMN conversation_id DROP DEFAULT;
