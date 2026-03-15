-- Add conversation_id to search_queries for chat-style grouping (valid 24h).
-- Format: conv_<ULID> (e.g. conv_01HVX8MZ7K8A9Q2R5T6YB3N4PD), VARCHAR(32) NOT NULL.
-- Column name is "datetime" (not ts). If your table still has "ts", run search_queries_ts_to_datetime_drop_project_id.sql first.
--
-- For existing rows: backfill with unique conv_<ULID> per row (e.g. via Python), then remove default if desired.

-- MySQL:
ALTER TABLE search_queries
  ADD COLUMN conversation_id VARCHAR(32) NOT NULL DEFAULT 'conv_LEGACY0000000000000000'
  AFTER datetime;

-- After backfilling existing rows with unique conversation_id values (optional):
-- ALTER TABLE search_queries ALTER COLUMN conversation_id DROP DEFAULT;

-- PostgreSQL:
-- ALTER TABLE search_queries ADD COLUMN conversation_id VARCHAR(32);
-- (Backfill existing rows with unique values, then:)
-- ALTER TABLE search_queries ALTER COLUMN conversation_id SET NOT NULL;
