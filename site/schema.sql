-- D1 schema for the GrokBot task dashboard.
-- One row holds the latest snapshot posted by the `st` CLI.
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL,
  updated INTEGER NOT NULL
);

-- Server metrics pushed by each host's cron (see server/grokbot-report.sh).
-- server-push.js also creates these on first use; rows older than 7 days are pruned.
CREATE TABLE IF NOT EXISTS server_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT NOT NULL, received INTEGER NOT NULL, cpu REAL, gpu REAL, vram REAL, ram REAL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS server_metrics_recv ON server_metrics (received);
CREATE INDEX IF NOT EXISTS server_metrics_host_recv ON server_metrics (host, received);
