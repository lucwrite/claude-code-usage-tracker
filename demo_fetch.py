"""Throwaway demo script for step 2 — proves fetch.py works against real
local data. Not part of the pipeline; safe to delete once verified."""

from fetch import fetch_daily, fetch_sessions

daily = fetch_daily()
print(f"=== fetch_daily(): {len(daily)} Claude-only days ===")
for d in daily:
    print(f"{d.date}  cost=${d.cost_usd:.2f}  tokens={d.total_tokens:,}  models={d.models_used}")

print()
sessions = fetch_sessions()
print(f"=== fetch_sessions(): {len(sessions)} Claude-only sessions ===")
for s in sessions[:5]:
    print(f"{s.session_id[:8]}...  date={s.date}  cost=${s.cost_usd:.2f}  tokens={s.total_tokens:,}")
print(f"... ({len(sessions) - 5} more)" if len(sessions) > 5 else "")

print()
print("=== Sanity check: 2026-07-06 (known mixed Claude+Codex day) ===")
july6 = next((d for d in daily if d.date == "2026-07-06"), None)
if july6:
    print(f"Claude-only cost for 2026-07-06: ${july6.cost_usd:.2f}  (unfiltered combined total was $103.56)")
else:
    print("2026-07-06 not found in Claude-filtered results (unexpected)")

print()
print("=== Sanity check: 2026-07-05 (known Codex-only day, should be dropped) ===")
july5 = next((d for d in daily if d.date == "2026-07-05"), None)
print("DROPPED correctly" if july5 is None else f"NOT dropped — found {july5}")
