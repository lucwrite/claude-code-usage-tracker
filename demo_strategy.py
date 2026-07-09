"""Throwaway demo/verification script for step 5. Not part of the
pipeline; safe to delete once verified. Reads the real usage.db."""

from strategy import evaluate_all, rule_approaching_weekly_limit, rule_cost_trending_up

print("=== evaluate_all() (no weekly limit configured) ===")
recs = evaluate_all()
if not recs:
    print("(no recommendations fired)")
for r in recs:
    print(f"[{r.severity}] {r.rule}: {r.message}")

print()
print(f"total recommendations: {len(recs)}")
by_rule = {}
for r in recs:
    by_rule[r.rule] = by_rule.get(r.rule, 0) + 1
print("breakdown by rule:", by_rule)

print()
print("=== rule_cost_trending_up() detail check ===")
from metrics import tokens_by_period
weeks = tokens_by_period("week")
print("all weeks in data:")
for w in weeks:
    print(f"  {w.period}  cost=${w.cost_usd:.2f}")
print("(current/last entry above is the in-progress week and should be excluded from the comparison)")
result = rule_cost_trending_up()
print("rule fired:" , bool(result))
for r in result:
    print(" ", r.message)

print()
print("=== rule_approaching_weekly_limit() with a sample $100/week limit ===")
result = rule_approaching_weekly_limit(weekly_limit_usd=100.0)
for r in result:
    print(f"[{r.severity}] {r.message}")
if not result:
    print("(did not fire at $100/week)")
