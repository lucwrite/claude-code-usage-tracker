"""Metrics computed from usage_snapshots -- step 4.

Reads only from the SQLite snapshot table, never from raw ccusage
output or by re-invoking ccusage. Returns plain dataclasses; no
display/formatting here -- that's the CLI layer (step 6).

IMPORTANT: usage_snapshots holds two independent groupings of the same
underlying usage -- kind='daily' (one row per day) and kind='session'
(one row per session). Every metric here filters to exactly one kind.
Summing across both would double-count, since a day's daily row already
includes the tokens from all that day's sessions.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path

from snapshot import DEFAULT_DB_PATH


@dataclass
class PeriodUsage:
    period: str  # date (day), "YYYY-Www" (week), or "YYYY-MM" (month)
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_tokens: int
    cost_usd: float


@dataclass
class CacheEfficiencyPoint:
    key: str  # date for the daily trend, session_id for per-session
    cache_read_tokens: int
    cache_creation_tokens: int
    efficiency: float | None  # None when a day/session had zero cache activity at all


@dataclass
class SessionDistribution:
    count: int
    median_tokens: float
    mean_tokens: float
    min_tokens: int
    max_tokens: int
    stdev_tokens: float


@dataclass
class SessionOutlier:
    session_id: str
    date: str
    total_tokens: int
    ratio_to_median: float


_GRANULARITY_EXPR = {
    "day": "date",
    "week": "strftime('%Y-W%W', date)",
    "month": "strftime('%Y-%m', date)",
}


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def tokens_by_period(granularity: str = "day", db_path: Path = DEFAULT_DB_PATH) -> list[PeriodUsage]:
    """Tokens and cost grouped by day, week, or month, from daily rows only."""
    if granularity not in _GRANULARITY_EXPR:
        raise ValueError(f"granularity must be one of {list(_GRANULARITY_EXPR)}")
    period_expr = _GRANULARITY_EXPR[granularity]

    conn = _connect(db_path)
    try:
        rows = conn.execute(f"""
            SELECT {period_expr} AS period,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(cache_read_tokens) AS cache_read_tokens,
                   SUM(cache_creation_tokens) AS cache_creation_tokens,
                   SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) AS total_tokens,
                   SUM(cost_usd) AS cost_usd
            FROM usage_snapshots
            WHERE kind = 'daily'
            GROUP BY period
            ORDER BY period
        """).fetchall()
    finally:
        conn.close()

    return [PeriodUsage(**dict(r)) for r in rows]


def cumulative_cost(granularity: str = "day", db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, float]]:
    """Running cumulative cost by period."""
    running = 0.0
    out = []
    for p in tokens_by_period(granularity, db_path):
        running += p.cost_usd
        out.append((p.period, round(running, 4)))
    return out


def _cache_efficiency(kind: str, key_column: str, db_path: Path) -> list[CacheEfficiencyPoint]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(f"""
            SELECT {key_column} AS key, cache_read_tokens, cache_creation_tokens
            FROM usage_snapshots
            WHERE kind = ?
            ORDER BY date
        """, (kind,)).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        total_cache = r["cache_read_tokens"] + r["cache_creation_tokens"]
        efficiency = r["cache_read_tokens"] / total_cache if total_cache > 0 else None
        out.append(CacheEfficiencyPoint(
            key=r["key"],
            cache_read_tokens=r["cache_read_tokens"],
            cache_creation_tokens=r["cache_creation_tokens"],
            efficiency=efficiency,
        ))
    return out


def cache_efficiency_by_day(db_path: Path = DEFAULT_DB_PATH) -> list[CacheEfficiencyPoint]:
    return _cache_efficiency("daily", "date", db_path)


def cache_efficiency_by_session(db_path: Path = DEFAULT_DB_PATH) -> list[CacheEfficiencyPoint]:
    return _cache_efficiency("session", "session_id", db_path)


def _session_totals(db_path: Path) -> list[sqlite3.Row]:
    conn = _connect(db_path)
    try:
        return conn.execute("""
            SELECT session_id, date,
                   input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens AS total_tokens
            FROM usage_snapshots
            WHERE kind = 'session'
        """).fetchall()
    finally:
        conn.close()


def session_token_distribution(db_path: Path = DEFAULT_DB_PATH) -> SessionDistribution | None:
    totals = [r["total_tokens"] for r in _session_totals(db_path)]
    if not totals:
        return None
    return SessionDistribution(
        count=len(totals),
        median_tokens=statistics.median(totals),
        mean_tokens=statistics.mean(totals),
        min_tokens=min(totals),
        max_tokens=max(totals),
        stdev_tokens=statistics.stdev(totals) if len(totals) > 1 else 0.0,
    )


def session_outliers(threshold: float = 2.0, db_path: Path = DEFAULT_DB_PATH) -> list[SessionOutlier]:
    """Sessions whose total tokens exceed `threshold` times the median session."""
    rows = _session_totals(db_path)
    totals = [r["total_tokens"] for r in rows]
    if not totals:
        return []
    med = statistics.median(totals)
    if med == 0:
        return []

    out = [
        SessionOutlier(
            session_id=r["session_id"],
            date=r["date"],
            total_tokens=r["total_tokens"],
            ratio_to_median=round(r["total_tokens"] / med, 2),
        )
        for r in rows
        if r["total_tokens"] / med > threshold
    ]
    out.sort(key=lambda o: -o.ratio_to_median)
    return out
