"""Static HTML dashboard -- renders the same data as `cli.py report` as a
self-contained HTML file and opens it in your default browser. No server,
no new dependencies (webbrowser is stdlib, same as everything else in
this project) -- regenerated fresh each time you run `cli.py dashboard`.

Language throughout is written for a non-technical reader: plain
sentences over jargon, dates over raw IDs, "how much you've used" over
"tokens". The one exception is small secondary text (session IDs, exact
counts) kept available for anyone who does want the detail.
"""

from __future__ import annotations

import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from energy import estimate_for_output_tokens, relatable_comparison, total_energy
from metrics import (
    cache_efficiency_by_day,
    friendly_date as _friendly_date,
    session_outliers,
    session_token_distribution,
    tokens_by_period,
)
from snapshot import DEFAULT_DB_PATH
from strategy import evaluate_all

OUTPUT_PATH = Path(__file__).parent / "report.html"

ACCENT = "#5b9dff"
GOOD = "#22c55e"
WARNING = "#f5a623"
CRITICAL = "#ef4444"
SERIES_2 = "#a78bfa"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _stat(value: str, label: str) -> str:
    return f'<div class="stat"><div class="stat-value">{value}</div><div class="stat-label">{label}</div></div>'


def _bar_row(label: str, value: float, max_value: float, color: str, value_label: str, wide_label: bool = False) -> str:
    pct = (value / max_value * 100) if max_value else 0
    row_class = "bar-row bar-row--wide" if wide_label else "bar-row"
    return f'''
    <div class="{row_class}">
      <span class="bar-label">{_esc(label)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:{pct:.2f}%; background:{color};"></div></div>
      <span class="bar-value">{_esc(value_label)}</span>
    </div>'''


def _period_section(granularity: str, periods) -> str:
    if not periods:
        return '<p class="empty">Nothing here yet.</p>'
    max_tokens = max(p.total_tokens for p in periods)
    rows = []
    for p in reversed(periods):
        _, mid_wh, _ = estimate_for_output_tokens(p.output_tokens)
        label = _friendly_date(p.period) if granularity == "day" else p.period
        value_label = f"${p.cost_usd:.2f} · ~{mid_wh:,.0f} Wh"
        rows.append(_bar_row(label, p.total_tokens, max_tokens, ACCENT, value_label))
    return f'<div class="bars">{"".join(rows)}</div>'


def _cache_efficiency_section() -> str:
    points = cache_efficiency_by_day()[-14:]
    if not points:
        return '<p class="empty">Nothing here yet.</p>'
    rows = "".join(
        _bar_row(
            _friendly_date(d.key), (d.efficiency or 0) * 100, 100,
            GOOD if (d.efficiency or 0) >= 0.8 else WARNING if (d.efficiency or 0) >= 0.5 else CRITICAL,
            f"{d.efficiency:.0%} reused" if d.efficiency is not None else "n/a",
        )
        for d in reversed(points)
    )
    return f'<div class="bars">{rows}</div>'


def _conversations_section(dist, outliers) -> str:
    if not dist:
        return '<p class="empty">No conversations tracked yet.</p>'
    _, typical_mid_wh, _ = estimate_for_output_tokens(dist.median_output_tokens)
    stat_html = (
        '<div class="stat-row">'
        + _stat(str(dist.count), "Conversations tracked")
        + _stat(f"{dist.median_tokens:,.0f}", "Typical conversation size (tokens)")
        + _stat(f"~{typical_mid_wh:,.1f} Wh", "Energy for a typical conversation")
        + _stat(str(len(outliers)), "Much longer than usual")
        + '</div>'
    )
    if not outliers:
        return stat_html
    max_tokens = outliers[0].total_tokens
    rows = "".join(
        _bar_row(
            _friendly_date(o.date), o.total_tokens, max_tokens, SERIES_2,
            f"{o.ratio_to_median:.0f}x typical · ~{estimate_for_output_tokens(o.output_tokens)[1]:,.1f} Wh",
        )
        for o in outliers[:15]
    )
    return (
        stat_html
        + '<p class="section-note">Conversations that ran unusually long compared to your typical one '
          '(Wh is this tool\'s mid-range estimate for that specific conversation):</p>'
        + f'<div class="bars">{rows}</div>'
    )


def _recommendations_section(weekly_limit_usd: float | None) -> str:
    recs = evaluate_all(weekly_limit_usd=weekly_limit_usd)
    if not recs:
        return '<p class="empty">Nothing to flag right now &mdash; your usage looks typical.</p>'
    items = "".join(
        f'<li class="rec rec-{r.severity}"><span class="rec-badge">{r.severity}</span>{_esc(r.message)}</li>'
        for r in recs
    )
    return f'<ul class="rec-list">{items}</ul>'


def _energy_section(daily_periods: list, dist, outliers) -> str:
    low, mid, high = total_energy(daily_periods)
    _, per_1k_mid, _ = estimate_for_output_tokens(1000)

    # Concrete activities -> energy, using real examples from your own
    # history where possible, so "what activity = what energy" has actual
    # answers instead of only an abstract aggregate total.
    activities: list[tuple[str, float]] = []
    if dist:
        _, typical_wh, _ = estimate_for_output_tokens(dist.median_output_tokens)
        activities.append(("A typical conversation for you", typical_wh))
    if outliers:
        biggest = max(outliers, key=lambda o: o.output_tokens)
        _, biggest_wh, _ = estimate_for_output_tokens(biggest.output_tokens)
        activities.append((f"Your longest conversation ({_friendly_date(biggest.date)})", biggest_wh))

    activity_html = ""
    if activities:
        max_wh = max(wh for _, wh in activities)
        rows = "".join(
            _bar_row(label, wh, max_wh, ACCENT, f"~{wh:,.1f} Wh", wide_label=True) for label, wh in activities
        )
        activity_html = f'''
    <p class="section-note">What specific activities cost, roughly (mid-range estimate):</p>
    <div class="bars">{rows}</div>
    <p class="section-note" style="margin-top:14px;">As a flat rate: roughly {per_1k_mid:.2f} Wh per 1,000 words
    Claude writes back to you (a few paragraphs) &mdash; the length of Claude's <em>reply</em> is what drives
    this estimate. How much you type barely matters, and reused context (checked/read, not regenerated)
    is close to free.</p>'''

    stats = (
        _stat(f"{low:,.0f} Wh", f"Low estimate &middot; {_esc(relatable_comparison(low))}")
        + _stat(f"{mid:,.0f} Wh", f"Middle estimate &middot; {_esc(relatable_comparison(mid))}")
        + _stat(f"{high:,.0f} Wh", f"High estimate &middot; {_esc(relatable_comparison(high))}")
    )
    return f'''{activity_html}
    <p class="section-note" style="margin-top:18px;">The "~X Wh" figure next to each bar in "How much you've
    used" above is this same estimate applied to that whole day/week/month. Totaled up across everything
    tracked:</p>
    <div class="stat-row">{stats}</div>
    <p class="energy-note">Why a range instead of one number: nobody outside Anthropic knows Claude's actual
    energy use per reply, so this borrows measurements from published research on other AI models and
    applies them to how much Claude wrote back to you (longer replies use more energy; how much you wrote
    to Claude barely matters, and reused context is close to free). Treat this as "roughly this ballpark,"
    not a precise number.</p>'''


def generate(
    weekly_limit_usd: float | None = None, db_path: Path = DEFAULT_DB_PATH, output_path: Path = OUTPUT_PATH
) -> Path:
    daily = tokens_by_period("day", db_path)
    weekly = tokens_by_period("week", db_path)
    monthly = tokens_by_period("month", db_path)

    total_tokens = sum(p.total_tokens for p in daily)
    total_cost = sum(p.cost_usd for p in daily)
    latest_eff = next((d.efficiency for d in reversed(cache_efficiency_by_day(db_path)) if d.efficiency is not None), None)
    dist = session_token_distribution(db_path)
    outliers = session_outliers(db_path=db_path)

    now = datetime.now(timezone.utc)
    try:
        generated_at = now.strftime("%b %-d, %Y at %H:%M UTC")
    except ValueError:
        # %-d (no-padding day) is glibc/macOS-only; fall back to the
        # portable zero-padded form on platforms that don't support it.
        generated_at = now.strftime("%b %d, %Y at %H:%M UTC")

    summary_stats = (
        _stat(f"{total_tokens:,}", "Total usage (tokens)")
        + _stat(f"${total_cost:,.2f}", "What this would cost, per use")
        + _stat(f"{latest_eff:.0%}" if latest_eff is not None else "n/a", "Context reused recently")
        + _stat(f"{dist.median_tokens:,.0f}" if dist else "n/a", "Typical conversation size")
    )

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Claude Code Usage</title>
<style>
  :root {{
    --bg: #0f1115; --paper: #171a21; --border: #262b36;
    --ink: #e8e9ed; --muted: #8b8f9c; --accent: {ACCENT};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .wrap {{ max-width: 900px; margin: 0 auto; padding: 36px 24px 70px; }}
  header {{ margin-bottom: 8px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); font-size: 13px; margin: 0 0 28px; }}
  .note {{
    background: rgba(91,157,255,0.08); border: 1px solid rgba(91,157,255,0.25);
    border-radius: 8px; padding: 10px 14px; font-size: 13px; color: var(--muted); margin-bottom: 28px; line-height: 1.6;
  }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 34px 0 14px; }}
  .card {{ background: var(--paper); border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px; }}
  .section-note {{ font-size: 13px; color: var(--muted); margin: 0 0 12px; }}

  .stat-row {{ display: flex; flex-wrap: wrap; gap: 24px; }}
  .stat-value {{ font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .stat-label {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}

  .tabbar {{ display: flex; gap: 6px; margin-bottom: 14px; }}
  .tabbtn {{
    cursor: pointer; font-size: 13px; font-weight: 600; padding: 6px 14px; border-radius: 999px;
    border: 1px solid var(--border); background: transparent; color: var(--muted);
  }}
  .tabbtn.active {{ background: var(--accent); border-color: var(--accent); color: #0f1115; }}
  .tabpanel {{ display: none; }}
  .tabpanel.active {{ display: block; }}

  .bar-row {{ display: grid; grid-template-columns: 90px 1fr 150px; align-items: center; gap: 10px; margin: 7px 0; }}
  .bar-row--wide {{ grid-template-columns: 220px 1fr 130px; }}
  .bar-label {{ font-size: 12.5px; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .bar-track {{ background: #0b0d11; border: 1px solid var(--border); border-radius: 4px; height: 14px; overflow: hidden; }}
  .bar-fill {{ height: 100%; }}
  .bar-value {{ font-size: 12.5px; color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; }}
  @media (max-width: 620px) {{ .bar-row {{ grid-template-columns: 1fr; gap: 2px; }} .bar-value {{ text-align: left; }} }}

  .rec-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }}
  .rec {{ font-size: 13px; line-height: 1.4; padding: 7px 12px; border-radius: 8px; border-left: 3px solid var(--border); background: #0b0d11; }}
  .rec-warning {{ border-left-color: {WARNING}; }}
  .rec-critical {{ border-left-color: {CRITICAL}; }}
  .rec-badge {{
    display: inline-block; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
    padding: 2px 7px; border-radius: 999px; margin-right: 10px; background: var(--border); color: var(--muted);
  }}
  .rec-warning .rec-badge {{ background: rgba(245,166,35,0.15); color: {WARNING}; }}
  .rec-critical .rec-badge {{ background: rgba(239,68,68,0.15); color: {CRITICAL}; }}

  .energy-note {{ margin-top: 12px; font-size: 13px; color: var(--muted); line-height: 1.6; }}
  .empty {{ color: var(--muted); font-size: 13px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Your Claude Code usage</h1>
    <p class="sub">Updated {generated_at} &middot; {dist.count if dist else 0} conversations tracked</p>
  </header>

  <div class="note">The dollar figures here are an estimate of what your usage would cost if you paid per use &mdash; not a real bill. If you're on a subscription plan, you pay the same price either way; think of this as a measure of how much you're using, not money spent.</div>

  <div class="card">
    <div class="stat-row">{summary_stats}</div>
  </div>

  <h2>How much you've used</h2>
  <div class="card">
    <div class="tabbar">
      <button class="tabbtn active" data-tab="t-day">Day</button>
      <button class="tabbtn" data-tab="t-week">Week</button>
      <button class="tabbtn" data-tab="t-month">Month</button>
    </div>
    <div id="t-day" class="tabpanel active">{_period_section("day", daily)}</div>
    <div id="t-week" class="tabpanel">{_period_section("week", weekly)}</div>
    <div id="t-month" class="tabpanel">{_period_section("month", monthly)}</div>
  </div>

  <h2>How much Claude could reuse (last 14 days)</h2>
  <div class="card">
    <p class="section-note">When Claude can reuse earlier parts of a conversation instead of reprocessing them, that's cheaper and faster. Higher is better.</p>
    {_cache_efficiency_section()}
  </div>

  <h2>Your conversations</h2>
  <div class="card">{_conversations_section(dist, outliers)}</div>

  <h2>Ways to use less</h2>
  <div class="card">{_recommendations_section(weekly_limit_usd)}</div>

  <h2>Energy estimate</h2>
  <div class="card">{_energy_section(daily, dist, outliers)}</div>
</div>

<script>
  document.querySelectorAll(".tabbtn").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(".tabbtn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tabpanel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    }});
  }});
</script>
</body>
</html>
'''

    output_path.write_text(html)
    return output_path


def generate_and_open(weekly_limit_usd: float | None = None, db_path: Path = DEFAULT_DB_PATH) -> Path:
    path = generate(weekly_limit_usd, db_path)
    webbrowser.open(f"file://{path}")
    return path
