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

from energy import estimate_for_output_tokens
from metrics import (
    cache_efficiency_by_day,
    cache_efficiency_by_session,
    friendly_date as _friendly_date,
    session_outliers,
    tokens_by_period,
    week_label as _week_label,
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
                message=f"On {_friendly_date(d.key)}, Claude only reused {d.efficiency:.0%} of earlier context "
                         f"instead of reprocessing it fresh (usually 90%+) — reloading large files or docs "
                         f"repeatedly in one sitting is the most common cause",
                context={"date": d.key, "efficiency": d.efficiency},
            ))

    for s in cache_efficiency_by_session(db_path):
        if s.efficiency is not None and s.efficiency < threshold:
            recs.append(Recommendation(
                rule="low_cache_reuse_session",
                severity="warning",
                message=f"A conversation on {_friendly_date(s.date)} only reused {s.efficiency:.0%} of earlier "
                         f"context instead of reprocessing it fresh (usually 90%+) — reloading large files or "
                         f"docs repeatedly in one sitting is the most common cause",
                context={"session_id": s.key, "date": s.date, "efficiency": s.efficiency},
            ))

    return recs


# --- Rule 2: session outliers ------------------------------------------

def rule_session_outliers(
    db_path: Path = DEFAULT_DB_PATH, threshold: float = 2.0, max_individual: int = 3
) -> list[Recommendation]:
    """Flags sessions whose total tokens exceed `threshold`x the median
    session. The median is recomputed from current data each call, so it
    naturally shifts as history grows -- not a fixed/hardcoded baseline.
    Only the `max_individual` worst offenders get their own message (a
    long history can have a dozen+ outliers, and repeating near-identical
    cards for all of them buries the actionable ones) -- the rest are
    folded into a single summary line. The full list still exists in the
    "Your conversations" section, so nothing is lost, just not repeated."""
    outliers = session_outliers(threshold, db_path)
    if not outliers:
        return []

    recs = []
    for o in outliers[:max_individual]:
        _, mid_wh, _ = estimate_for_output_tokens(o.output_tokens)
        recs.append(Recommendation(
            rule="session_outlier",
            severity="warning",
            message=f"The conversation on {_friendly_date(o.date)} ran about {o.ratio_to_median:.0f}x longer "
                     f"than a typical one for you ({o.total_tokens:,} tokens, ~{mid_wh:,.1f} Wh) — for unrelated "
                     f"tasks, starting a fresh conversation instead of one long thread tends to use less",
            context={"session_id": o.session_id, "date": o.date, "ratio": o.ratio_to_median},
        ))

    rest = outliers[max_individual:]
    if rest:
        extra_wh = sum(estimate_for_output_tokens(o.output_tokens)[1] for o in rest)
        recs.append(Recommendation(
            rule="session_outlier_summary",
            severity="info",
            message=f"{len(rest)} more conversation{'s' if len(rest) != 1 else ''} also ran unusually long "
                     f"(~{extra_wh:,.1f} Wh combined) — see \"Your conversations\" below for the full list",
            context={"count": len(rest)},
        ))
    return recs


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
    if len(weeks) < 2:
        return []
    # Exclude the current week only if it's actually the one containing
    # today -- weeks[-1] isn't reliably "in progress" (e.g. right after a
    # week just ended, before any new-week data exists, weeks[-1] is
    # already complete; blindly dropping it would compare the wrong pair).
    today_week_label = _week_label(_date.today().isoformat())
    complete_weeks = [w for w in weeks if w.period != today_week_label]
    if len(complete_weeks) < 2:
        return []
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
        message=f"Your usage value jumped {cost_change:.0%} from last week to this week "
                 f"(${prev_week.cost_usd:.2f} → ${last_week.cost_usd:.2f}) without Claude reusing more "
                 f"context to offset it — worth a quick look at what changed",
        context={"prev_week": prev_week.period, "last_week": last_week.period, "cost_change": cost_change},
    )]


def _avg_efficiency_in_week(daily_eff, target_week_label: str) -> float | None:
    # tokens_by_period("week") groups by the same label _week_label computes;
    # recompute it per day to match efficiency points into the same week.
    matches = [d.efficiency for d in daily_eff if _week_label(d.key) == target_week_label and d.efficiency is not None]
    return statistics.mean(matches) if matches else None


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
    if weekly_limit_usd is None or weekly_limit_usd <= 0:
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
        message=f"You've used ${current_week.cost_usd:.2f} of the ${weekly_limit_usd:.2f} weekly budget "
                 f"you set for yourself ({fraction:.0%}) — pace yourself for the rest of the week",
        context={"week": current_week.period, "spent": current_week.cost_usd, "limit": weekly_limit_usd},
    )]


RULES = [rule_low_cache_reuse, rule_session_outliers, rule_cost_trending_up, rule_approaching_weekly_limit]


def evaluate_all(db_path: Path = DEFAULT_DB_PATH, weekly_limit_usd: float | None = None) -> list[Recommendation]:
    """Actually iterates RULES (previously this hardcoded the same four
    calls a second time, so RULES could silently drift out of sync with
    what's really evaluated -- a rule added to one and not the other
    would be silently skipped). Only rule_approaching_weekly_limit needs
    the extra weekly_limit_usd argument; every other rule takes just db_path."""
    recs: list[Recommendation] = []
    for rule in RULES:
        if rule is rule_approaching_weekly_limit:
            recs.extend(rule(db_path, weekly_limit_usd=weekly_limit_usd))
        else:
            recs.extend(rule(db_path))
    return recs
