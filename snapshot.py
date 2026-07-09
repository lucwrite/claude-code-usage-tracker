"""SQLite snapshot writer -- step 3.

Persists Claude-Code-only usage records (from fetch.py) into a local
SQLite database, so "usage over time" trends survive across runs even
though ccusage itself only reports current logs, not history.

Idempotent via upsert, not insert-once: re-running a fetch for a date or
session that's already recorded updates that row in place. This matters
for "today" and any session still in progress -- their totals grow
between runs, so true insert-once-only semantics would freeze those rows
at an incomplete value forever (see the spec discussion this came out of).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fetch import DailyUsage, SessionUsage

DEFAULT_DB_PATH = Path(__file__).parent / "usage.db"

# Uniqueness is scoped per row-kind via partial indexes rather than one
# composite (date, session_id) constraint, because the two kinds have
# different identity: a daily row's identity is its date; a session row's
# identity is its session_id -- NOT its date, since a long session's
# lastActivity can roll over to the next calendar day between snapshot
# runs. A composite constraint would let that produce a duplicate row.
SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    date                    DATE      NOT NULL,
    session_id              TEXT,                        -- NULL for daily rows
    kind                    TEXT      NOT NULL CHECK (kind IN ('daily', 'session')),
    project                 TEXT,                        -- always NULL today; ccusage exposes no project breakdown
    input_tokens            INTEGER   NOT NULL,
    output_tokens           INTEGER   NOT NULL,
    cache_read_tokens       INTEGER   NOT NULL,
    cache_creation_tokens   INTEGER   NOT NULL,
    cost_usd                REAL      NOT NULL,
    recorded_at             TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_snapshots_daily_date
    ON usage_snapshots (date) WHERE kind = 'daily';

CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_snapshots_session_id
    ON usage_snapshots (session_id) WHERE kind = 'session';

CREATE INDEX IF NOT EXISTS idx_usage_snapshots_date ON usage_snapshots (date);
"""

_UPSERT_DAILY_SQL = """
INSERT INTO usage_snapshots
    (date, session_id, kind, project, input_tokens, output_tokens,
     cache_read_tokens, cache_creation_tokens, cost_usd, recorded_at)
VALUES (?, NULL, 'daily', NULL, ?, ?, ?, ?, ?, ?)
ON CONFLICT (date) WHERE kind = 'daily' DO UPDATE SET
    input_tokens          = excluded.input_tokens,
    output_tokens         = excluded.output_tokens,
    cache_read_tokens     = excluded.cache_read_tokens,
    cache_creation_tokens = excluded.cache_creation_tokens,
    cost_usd              = excluded.cost_usd,
    recorded_at           = excluded.recorded_at
"""

_UPSERT_SESSION_SQL = """
INSERT INTO usage_snapshots
    (date, session_id, kind, project, input_tokens, output_tokens,
     cache_read_tokens, cache_creation_tokens, cost_usd, recorded_at)
VALUES (?, ?, 'session', NULL, ?, ?, ?, ?, ?, ?)
ON CONFLICT (session_id) WHERE kind = 'session' DO UPDATE SET
    date                  = excluded.date,
    input_tokens          = excluded.input_tokens,
    output_tokens         = excluded.output_tokens,
    cache_read_tokens     = excluded.cache_read_tokens,
    cache_creation_tokens = excluded.cache_creation_tokens,
    cost_usd              = excluded.cost_usd,
    recorded_at           = excluded.recorded_at
"""


@contextmanager
def _connect(db_path: Path = DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with _connect(db_path):
        pass  # schema creation happens in _connect itself


def snapshot_daily(records: list[DailyUsage], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Upserts daily records. Returns the number of rows written."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.executemany(
            _UPSERT_DAILY_SQL,
            [
                (d.date, d.input_tokens, d.output_tokens,
                 d.cache_read_tokens, d.cache_creation_tokens, d.cost_usd, now)
                for d in records
            ],
        )
        return len(records)


def snapshot_sessions(records: list[SessionUsage], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Upserts session records. Returns the number of rows written."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.executemany(
            _UPSERT_SESSION_SQL,
            [
                (s.date, s.session_id, s.input_tokens, s.output_tokens,
                 s.cache_read_tokens, s.cache_creation_tokens, s.cost_usd, now)
                for s in records
            ],
        )
        return len(records)
