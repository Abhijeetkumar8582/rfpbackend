-- MySQL: Add confidence column to rfpquestions table.
-- Stores a JSON array of numbers: one confidence value per question, same order as questions/answers.
-- JSON type has no default (MySQL strict mode: BLOB/TEXT/JSON can't have default).
-- Run this if the column was not added by app startup migration.

ALTER TABLE rfpquestions ADD COLUMN confidence JSON;
