"""Strategy rule engine -- step 5.

Each rule is a plain function: reads from metrics.py, returns zero or
more Recommendation objects. Add a new rule by writing a new function
with this shape and adding it to RULES -- matches the spec's "simple
list of {condition, message}, easy to extend."
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from metrics import (
    cache_efficiency_by_day,
    cache_efficiency_by_session,
    session_outliers,
    tokens_by_period,
)
from snapshot import DEFAULT_DB_PATH


@dataclass
class Recommendation:
    rule: str
    severity: str  # "info" | "warning"
    message: str
    context: dict


# --- Rule 1: low cache reuse -----------------------------------------

def rule_low_cache_reuse(
    db_path: Path = DEFAULT_DB_PATH, threshold: float = 0.5, lookback_days: int = 14
) -> list[Recommendation]:
    """Flags individual days/sessions whose cache-read ratio is below
    `threshold`. Days limited to the most recent `lookback_days` so this
    stays about what's actionable now, not a dredge through all history;
    sessions are checked across the full history, since there are far
    fewer of them and each is a discrete, still-relevant unit of work."""
    recs = []

    daily = cache_efficiency_by_day(db_path)[-lookback_days:]
    for d in daily:
        if d.efficiency is not None and d.efficiency < threshold:
            recs.append(Recommendation(
                rule="low_cache_reuse_day",
                severity="warning",
                message=f"Low cache reuse on {d.key} ({d.efficiency:.0%}) — consider fewer large context reloads",
                context={"date": d.key, "efficiency": d.efficiency},
            ))

    for s in cache_efficiency_by_session(db_path):
        if s.efficiency is not None and s.efficiency < threshold:
            recs.append(Recommendation(
                rule="low_cache_reuse_session",
                severity="warning",
                message=f"Low cache reuse in session {s.key[:8]}... ({s.efficiency:.0%}) — consider fewer large context reloads",
                context={"session_id": s.key, "efficiency": s.efficiency},
            ))

    return recs


# --- Rule 2: session outliers ------------------------------------------

def rule_session_outliers(db_path: Path = DEFAULT_DB_PATH, threshold: float = 2.0) -> list[Recommendation]:
    """Flags sessions whose total tokens exceed `threshold`x the median
    session. The median is recomputed from current data each call, so it
    naturally shifts as history grows -- not a fixed/hardcoded baseline."""
    return [
        Recommendation(
            rule="session_outlier",
            severity="warning",
            message=f"Session {o.session_id[:8]}... on {o.date} used {o.total_tokens:,} tokens "
                     f"({o.ratio_to_median}x the median) — consider splitting into smaller tasks",
            context={"session_id": o.session_id, "date": o.date, "ratio": o.ratio_to_median},
        )
        for o in session_outliers(threshold, db_path)
    ]


# --- Rule 3: cost rising without better cache efficiency ---------------

def rule_cost_trending_up(
    db_path: Path = DEFAULT_DB_PATH, rise_threshold: float = 0.20, efficiency_flat_band: float = 0.03
) -> list[Recommendation]:
    """Compares the last two fully-completed weeks (the current
    in-progress week is excluded -- comparing a partial week against a
    complete one would show a misleading swing). Fires only when cost
    rose more than `rise_threshold` AND cache efficiency didn't improve
    by more than `efficiency_flat_band` -- a cost rise alongside a real
    efficiency improvement usually just means more work got done, not
    waste."""
    weeks = tokens_by_period("week", db_path)
    if len(weeks) < 3:
        return []  # need at least 2 complete weeks + the current partial one to exclude it
    complete_weeks = weeks[:-1]
    prev_week, last_week = complete_weeks[-2], complete_weeks[-1]

    if prev_week.cost_usd <= 0:
        return []
    cost_change = (last_week.cost_usd - prev_week.cost_usd) / prev_week.cost_usd
    if cost_change <= rise_threshold:
        return []

    daily_eff = cache_efficiency_by_day(db_path)
    prev_eff = _avg_efficiency_in_week(daily_eff, prev_week.period)
    last_eff = _avg_efficiency_in_week(daily_eff, last_week.period)
    if prev_eff is None or last_eff is None:
        return []
    eff_change = last_eff - prev_eff
    if eff_change > efficiency_flat_band:
        return []  # efficiency meaningfully improved -- rising cost is likely justified

    return [Recommendation(
        rule="cost_trending_up",
        severity="warning",
        message=f"Est. API cost rose {cost_change:.0%} week-over-week (${prev_week.cost_usd:.2f} → ${last_week.cost_usd:.2f}) "
                 f"without better cache reuse ({prev_eff:.0%} → {last_eff:.0%}) — review recent sessions",
        context={"prev_week": prev_week.period, "last_week": last_week.period, "cost_change": cost_change},
    )]


def _avg_efficiency_in_week(daily_eff, week_label: str) -> float | None:
    # tokens_by_period("week") groups by strftime('%Y-W%W', date); recompute
    # the same label per day to match efficiency points into the same week.
    matches = [d.efficiency for d in daily_eff if _week_label(d.key) == week_label and d.efficiency is not None]
    return statistics.mean(matches) if matches else None


def _week_label(date_str: str) -> str:
    y, m, d = (int(x) for x in date_str.split("-"))
    return _date(y, m, d).strftime("%Y-W%W")


# --- Rule 4: approaching a configured weekly limit ----------------------

def rule_approaching_weekly_limit(
    db_path: Path = DEFAULT_DB_PATH, weekly_limit_usd: float | None = None, warn_at: float = 0.8
) -> list[Recommendation]:
    """`weekly_limit_usd` is YOUR personal spending ceiling, not Anthropic's
    account limit -- Claude Code's real rate limit runs on rolling 5-hour
    session blocks (see `ccusage blocks --active`), which isn't something
    knowable from usage_snapshots, and neither ccusage nor this tool can
    see your actual plan entitlement. This rule is just a self-chosen
    budget alarm; no default, no-op until you pass a number in."""
    if weekly_limit_usd is None:
        return []

    weeks = tokens_by_period("week", db_path)
    if not weeks:
        return []
    current_week = weeks[-1]
    fraction = current_week.cost_usd / weekly_limit_usd
    if fraction < warn_at:
        return []

    return [Recommendation(
        rule="approaching_weekly_limit",
        severity="warning" if fraction < 1.0 else "critical",
        message=f"${current_week.cost_usd:.2f} (est. API-equivalent) of your ${weekly_limit_usd:.2f} "
                 f"self-set weekly budget used ({fraction:.0%}) — pace remaining work",
        context={"week": current_week.period, "spent": current_week.cost_usd, "limit": weekly_limit_usd},
    )]


RULES = [rule_low_cache_reuse, rule_session_outliers, rule_cost_trending_up, rule_approaching_weekly_limit]


def evaluate_all(db_path: Path = DEFAULT_DB_PATH, weekly_limit_usd: float | None = None) -> list[Recommendation]:
    recs: list[Recommendation] = []
    recs.extend(rule_low_cache_reuse(db_path))
    recs.extend(rule_session_outliers(db_path))
    recs.extend(rule_cost_trending_up(db_path))
    recs.extend(rule_approaching_weekly_limit(db_path, weekly_limit_usd))
    return recs
