-- D1 schema for the GrokBot task dashboard.
-- One row holds the latest snapshot posted by the `st` CLI.
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL,
  updated INTEGER NOT NULL
);
