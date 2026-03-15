-- Rename search_queries.ts to datetime and remove project_id.
-- Run this first if your table still has columns ts and project_id; then run add_search_queries_conversation_id.sql.
-- MySQL: drop the foreign key before dropping the column.

-- MySQL 8.0.3+:
ALTER TABLE search_queries RENAME COLUMN ts TO datetime;
ALTER TABLE search_queries DROP FOREIGN KEY fk_search_queries_project_id;
ALTER TABLE search_queries DROP COLUMN project_id;

-- PostgreSQL:
-- ALTER TABLE search_queries RENAME COLUMN ts TO datetime;
-- ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS search_queries_project_id_fkey;
-- ALTER TABLE search_queries DROP COLUMN project_id;
