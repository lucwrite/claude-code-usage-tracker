"""Throwaway demo/verification script for step 4. Not part of the
pipeline; safe to delete once verified. Reads the real usage.db seeded
in step 3."""

from metrics import (
    cache_efficiency_by_day,
    cumulative_cost,
    session_outliers,
    session_token_distribution,
    tokens_by_period,
)

print("=== tokens_by_period('week') ===")
weekly = tokens_by_period("week")
for w in weekly:
    print(f"{w.period}  tokens={w.total_tokens:,}  cost=${w.cost_usd:.2f}")

print()
print("=== tokens_by_period('month') ===")
for m in tokens_by_period("month"):
    print(f"{m.period}  tokens={m.total_tokens:,}  cost=${m.cost_usd:.2f}")

print()
print("=== cumulative_cost('day') -- last 5 ===")
for period, running in cumulative_cost("day")[-5:]:
    print(f"{period}  cumulative=${running:.2f}")

print()
print("=== cache_efficiency_by_day() -- last 5 ===")
for c in cache_efficiency_by_day()[-5:]:
    eff = f"{c.efficiency:.1%}" if c.efficiency is not None else "n/a"
    print(f"{c.key}  cache_read={c.cache_read_tokens:,}  cache_creation={c.cache_creation_tokens:,}  efficiency={eff}")

print()
print("=== session_token_distribution() ===")
dist = session_token_distribution()
print(dist)

print()
print("=== session_outliers(threshold=2.0) ===")
outliers = session_outliers()
for o in outliers:
    print(f"{o.session_id[:8]}...  date={o.date}  tokens={o.total_tokens:,}  {o.ratio_to_median}x median")
print(f"({len(outliers)} sessions exceed 2x the median of {dist.median_tokens:,.0f} tokens)")

print()
print("=== Sanity check: sum of weekly tokens should equal sum of daily-row total ===")
weekly_sum = sum(w.total_tokens for w in weekly)
daily_sum = sum(d.total_tokens for d in tokens_by_period("day"))
print(f"weekly_sum={weekly_sum:,}  daily_sum={daily_sum:,}  {'MATCH' if weekly_sum == daily_sum else 'MISMATCH'}")
