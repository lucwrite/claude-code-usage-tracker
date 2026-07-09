"""Throwaway demo/verification script for step 3. Not part of the
pipeline; safe to delete once verified. Uses a separate test DB so it
never touches real snapshot history in usage.db."""

import sqlite3
from pathlib import Path

from fetch import DailyUsage, SessionUsage, fetch_daily, fetch_sessions
from snapshot import snapshot_daily, snapshot_sessions

TEST_DB = Path(__file__).parent / "test_usage.db"
TEST_DB.unlink(missing_ok=True)

print("=== Real fetch -> snapshot, run 1 ===")
daily = fetch_daily()
sessions = fetch_sessions()
n1 = snapshot_daily(daily, TEST_DB)
n2 = snapshot_sessions(sessions, TEST_DB)
print(f"snapshotted {n1} daily rows, {n2} session rows")

conn = sqlite3.connect(TEST_DB)
row_count_1 = conn.execute("SELECT COUNT(*) FROM usage_snapshots").fetchone()[0]
print(f"table row count after run 1: {row_count_1}")

print()
print("=== Re-running the exact same fetch -> snapshot (simulates a cron re-run) ===")
snapshot_daily(fetch_daily(), TEST_DB)
snapshot_sessions(fetch_sessions(), TEST_DB)
row_count_2 = conn.execute("SELECT COUNT(*) FROM usage_snapshots").fetchone()[0]
print(f"table row count after run 2: {row_count_2}")
print("PASS: no duplicate rows" if row_count_1 == row_count_2 else f"FAIL: row count changed ({row_count_1} -> {row_count_2})")

print()
print("=== Upsert correctness: simulate 'today' getting more usage between runs ===")
today = daily[-1].date  # most recent day in the real data
before = conn.execute("SELECT cost_usd, recorded_at FROM usage_snapshots WHERE date = ? AND kind = 'daily'", (today,)).fetchone()
print(f"stored cost for {today} before update: ${before[0]:.4f}  (recorded_at={before[1]})")

fake_more_usage = DailyUsage(
    date=today, input_tokens=999, output_tokens=999, cache_read_tokens=999,
    cache_creation_tokens=999, cost_usd=before[0] + 5.00, total_tokens=3996,
    models_used=["claude-sonnet-5"],
)
snapshot_daily([fake_more_usage], TEST_DB)
after = conn.execute("SELECT cost_usd, recorded_at FROM usage_snapshots WHERE date = ? AND kind = 'daily'", (today,)).fetchone()
print(f"stored cost for {today} after simulated update: ${after[0]:.4f}  (recorded_at={after[1]})")
print("PASS: row updated in place, no duplicate" if after[0] == before[0] + 5.00 else "FAIL")
row_count_3 = conn.execute("SELECT COUNT(*) FROM usage_snapshots").fetchone()[0]
print(f"row count still {row_count_3} (should equal {row_count_2})" )

print()
print("=== Session date-rollover edge case: same session_id, different date across runs ===")
fake_session_v1 = SessionUsage(
    session_id="test-rollover-session", date="2026-07-09", last_activity="2026-07-09T23:58:00Z",
    input_tokens=100, output_tokens=100, cache_read_tokens=100, cache_creation_tokens=100,
    cost_usd=1.00, total_tokens=400, models_used=["claude-sonnet-5"],
)
fake_session_v2 = SessionUsage(
    session_id="test-rollover-session", date="2026-07-10", last_activity="2026-07-10T00:05:00Z",
    input_tokens=250, output_tokens=250, cache_read_tokens=250, cache_creation_tokens=250,
    cost_usd=2.50, total_tokens=1000, models_used=["claude-sonnet-5"],
)
snapshot_sessions([fake_session_v1], TEST_DB)
count_after_v1 = conn.execute("SELECT COUNT(*) FROM usage_snapshots WHERE session_id = ?", ("test-rollover-session",)).fetchone()[0]
snapshot_sessions([fake_session_v2], TEST_DB)  # simulates the session continuing past midnight
rows_after_v2 = conn.execute("SELECT date, cost_usd FROM usage_snapshots WHERE session_id = ?", ("test-rollover-session",)).fetchall()
print(f"rows for this session_id after date rollover: {rows_after_v2}")
print("PASS: exactly one row, date updated to 2026-07-10" if rows_after_v2 == [("2026-07-10", 2.50)] else "FAIL: got duplicate or stale row")

conn.close()
TEST_DB.unlink()
print()
print("(test_usage.db removed)")
