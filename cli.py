"""CLI entry point -- step 6.

Usage:
    python3 cli.py sync
    python3 cli.py report
    python3 cli.py report --granularity week
    python3 cli.py report --weekly-limit 100
"""

from __future__ import annotations

import argparse
import sys

from energy import energy_by_period, relatable_comparison, total_energy
from fetch import CcusageError, fetch_daily, fetch_sessions
from metrics import (
    cache_efficiency_by_day,
    session_outliers,
    session_token_distribution,
    tokens_by_period,
)
from snapshot import DEFAULT_DB_PATH, snapshot_daily, snapshot_sessions
from strategy import evaluate_all


def _print_table(headers: list[str], rows: list[tuple]) -> None:
    if not rows:
        print("(no rows)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(cells):
        return "  ".join(
            str(c).ljust(widths[i]) if i == 0 else str(c).rjust(widths[i])
            for i, c in enumerate(cells)
        )

    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))


def cmd_sync(args: argparse.Namespace) -> int:
    print("Fetching from ccusage...")
    try:
        daily = fetch_daily()
        sessions = fetch_sessions()
    except CcusageError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    n_daily = snapshot_daily(daily)
    n_sessions = snapshot_sessions(sessions)
    print(f"Synced {n_daily} daily rows, {n_sessions} session rows into {DEFAULT_DB_PATH}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    periods = tokens_by_period(args.granularity)
    if not periods:
        print("No data yet -- run `python3 cli.py sync` first.")
        return 1

    print(
        "\nNote: \"cost\" below is what your usage would cost at pay-as-you-go API "
        "rates -- not a real bill. On a flat-rate plan (Pro/Max), you pay the same "
        "subscription price regardless; this is a relative yardstick for usage "
        "intensity, not money actually charged."
    )

    print(f"\n=== Usage by {args.granularity} ===")
    _print_table(
        ["Period", "Tokens", "Est. API Cost"],
        [(p.period, f"{p.total_tokens:,}", f"${p.cost_usd:.2f}") for p in periods],
    )

    print("\n=== Cache efficiency (last 7 days) ===")
    _print_table(
        ["Date", "Cache read", "Cache creation", "Efficiency"],
        [
            (d.key, f"{d.cache_read_tokens:,}", f"{d.cache_creation_tokens:,}",
             f"{d.efficiency:.0%}" if d.efficiency is not None else "n/a")
            for d in cache_efficiency_by_day()[-7:]
        ],
    )

    dist = session_token_distribution()
    if dist:
        print(f"\n=== Sessions ({dist.count} total) ===")
        print(f"median {dist.median_tokens:,.0f} tokens | mean {dist.mean_tokens:,.0f} | max {dist.max_tokens:,.0f}")
        outliers = session_outliers()
        if outliers:
            print(f"\n{len(outliers)} outlier session(s) (>2x median):")
            _print_table(
                ["Session", "Date", "Tokens", "x Median"],
                [(o.session_id[:8] + "...", o.date, f"{o.total_tokens:,}", f"{o.ratio_to_median}x") for o in outliers[:10]],
            )
            if len(outliers) > 10:
                print(f"... and {len(outliers) - 10} more")

    if args.energy:
        low, mid, high = total_energy(periods)
        print(f"\n=== Estimated energy (rough, NOT Claude-specific -- see README) ===")
        print(f"Low estimate:   {low:,.1f} Wh  ({relatable_comparison(low)})")
        print(f"Mid estimate:   {mid:,.1f} Wh  ({relatable_comparison(mid)})")
        print(f"High estimate:  {high:,.1f} Wh  ({relatable_comparison(high)})")
        print(
            "Derived from published research on OTHER models' measured joules-per-output-token\n"
            "(0.39-7.2 J/token range); input/cache tokens excluded from the estimate since\n"
            "research found they're <=3.4% of real inference energy. This is an order-of-\n"
            "magnitude proxy, not a measurement of Claude's actual energy use."
        )

    recs = evaluate_all(weekly_limit_usd=args.weekly_limit)
    print(f"\n=== Recommendations ({len(recs)}) ===")
    if not recs:
        print("Nothing to flag right now.")
    else:
        for r in recs:
            marker = "!!" if r.severity == "critical" else "! "
            print(f"{marker} {r.message}")
    if args.weekly_limit is None:
        print("\n(pass --weekly-limit <amount> to enable the plan-limit warning rule)")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="cli.py", description="Claude Code usage tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Fetch from ccusage and snapshot into SQLite")
    p_sync.set_defaults(func=cmd_sync)

    p_report = sub.add_parser("report", help="Show metrics and recommendations")
    p_report.add_argument("--granularity", choices=["day", "week", "month"], default="day")
    p_report.add_argument("--weekly-limit", type=float, default=None, help="Your weekly $ budget")
    p_report.add_argument(
        "--energy", action="store_true",
        help="Show a rough, non-Claude-specific energy-use estimate (see README for sourcing/caveats)",
    )
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
