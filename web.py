"""Static HTML dashboard -- renders the same data as `cli.py report` as a
self-contained HTML file and opens it in your default browser. No server,
no new dependencies (webbrowser is stdlib, same as everything else in
this project) -- regenerated fresh each time you run `cli.py dashboard`.
"""

from __future__ import annotations

import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from energy import total_energy, relatable_comparison
from metrics import cache_efficiency_by_day, session_outliers, session_token_distribution, tokens_by_period
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


def _bar_row(label: str, value: float, max_value: float, color: str, value_label: str) -> str:
    pct = (value / max_value * 100) if max_value else 0
    return f'''
    <div class="bar-row">
      <span class="bar-label">{_esc(label)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:{pct:.2f}%; background:{color};"></div></div>
      <span class="bar-value">{_esc(value_label)}</span>
    </div>'''


def _period_section(tab_id: str, periods) -> str:
    if not periods:
        return '<p class="empty">No data.</p>'
    max_tokens = max(p.total_tokens for p in periods)
    rows = "".join(
        _bar_row(p.period, p.total_tokens, max_tokens, ACCENT, f"{p.total_tokens:,} tok / ${p.cost_usd:.2f}")
        for p in reversed(periods)
    )
    return f'<div class="bars">{rows}</div>'


def _cache_efficiency_section() -> str:
    points = cache_efficiency_by_day()[-14:]
    if not points:
        return '<p class="empty">No data.</p>'
    rows = "".join(
        _bar_row(
            d.key, (d.efficiency or 0) * 100, 100,
            GOOD if (d.efficiency or 0) >= 0.8 else WARNING if (d.efficiency or 0) >= 0.5 else CRITICAL,
            f"{d.efficiency:.0%}" if d.efficiency is not None else "n/a",
        )
        for d in reversed(points)
    )
    return f'<div class="bars">{rows}</div>'


def _outliers_section() -> str:
    dist = session_token_distribution()
    if not dist:
        return '<p class="empty">No sessions yet.</p>'
    outliers = session_outliers()
    stat_html = (
        f'<div class="stat-row">'
        f'<div class="stat"><div class="stat-value">{dist.count}</div><div class="stat-label">Sessions</div></div>'
        f'<div class="stat"><div class="stat-value">{dist.median_tokens:,.0f}</div><div class="stat-label">Median tokens</div></div>'
        f'<div class="stat"><div class="stat-value">{dist.max_tokens:,.0f}</div><div class="stat-label">Max tokens</div></div>'
        f'<div class="stat"><div class="stat-value">{len(outliers)}</div><div class="stat-label">Outliers (&gt;2x median)</div></div>'
        f'</div>'
    )
    if not outliers:
        return stat_html
    max_tokens = outliers[0].total_tokens
    rows = "".join(
        _bar_row(f"{o.session_id[:8]}... ({o.date})", o.total_tokens, max_tokens, SERIES_2, f"{o.ratio_to_median}x median")
        for o in outliers[:15]
    )
    return stat_html + f'<div class="bars">{rows}</div>'


def _recommendations_section(weekly_limit_usd: float | None) -> str:
    recs = evaluate_all(weekly_limit_usd=weekly_limit_usd)
    if not recs:
        return '<p class="empty">Nothing to flag right now.</p>'
    items = "".join(
        f'<li class="rec rec-{r.severity}"><span class="rec-badge">{r.severity}</span>{_esc(r.message)}</li>'
        for r in recs
    )
    return f'<ul class="rec-list">{items}</ul>'


def _energy_section() -> str:
    periods = tokens_by_period("day")
    low, mid, high = total_energy(periods)
    return f'''
    <details class="energy-details">
      <summary>Rough energy estimate (click to expand -- not Claude-specific, see README)</summary>
      <div class="stat-row" style="margin-top:12px;">
        <div class="stat"><div class="stat-value">{low:,.0f} Wh</div><div class="stat-label">Low &middot; {_esc(relatable_comparison(low))}</div></div>
        <div class="stat"><div class="stat-value">{mid:,.0f} Wh</div><div class="stat-label">Mid &middot; {_esc(relatable_comparison(mid))}</div></div>
        <div class="stat"><div class="stat-value">{high:,.0f} Wh</div><div class="stat-label">High &middot; {_esc(relatable_comparison(high))}</div></div>
      </div>
      <p class="energy-note">Derived from published research on OTHER models' measured joules-per-output-token
      (0.39&ndash;7.2 J/token range); input/cache tokens excluded since research found they're &le;3.4% of real
      inference energy. An order-of-magnitude proxy, not a measurement of Claude's actual energy use.</p>
    </details>'''


def generate(weekly_limit_usd: float | None = None, db_path: Path = DEFAULT_DB_PATH) -> Path:
    daily = tokens_by_period("day", db_path)
    weekly = tokens_by_period("week", db_path)
    monthly = tokens_by_period("month", db_path)

    total_tokens = sum(p.total_tokens for p in daily)
    total_cost = sum(p.cost_usd for p in daily)
    latest_eff = next((d.efficiency for d in reversed(cache_efficiency_by_day(db_path)) if d.efficiency is not None), None)
    dist = session_token_distribution(db_path)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code Usage Dashboard</title>
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
    border-radius: 8px; padding: 10px 14px; font-size: 13px; color: var(--muted); margin-bottom: 28px;
  }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 34px 0 14px; }}
  .card {{ background: var(--paper); border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px; }}

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

  .bar-row {{ display: grid; grid-template-columns: 170px 1fr 150px; align-items: center; gap: 10px; margin: 7px 0; }}
  .bar-label {{ font-size: 12.5px; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .bar-track {{ background: #0b0d11; border: 1px solid var(--border); border-radius: 4px; height: 14px; overflow: hidden; }}
  .bar-fill {{ height: 100%; }}
  .bar-value {{ font-size: 12.5px; color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; }}
  @media (max-width: 620px) {{ .bar-row {{ grid-template-columns: 1fr; gap: 2px; }} .bar-value {{ text-align: left; }} }}

  .rec-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }}
  .rec {{ font-size: 13.5px; padding: 10px 14px; border-radius: 8px; border-left: 3px solid var(--border); background: #0b0d11; }}
  .rec-warning {{ border-left-color: {WARNING}; }}
  .rec-critical {{ border-left-color: {CRITICAL}; }}
  .rec-badge {{
    display: inline-block; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
    padding: 2px 7px; border-radius: 999px; margin-right: 10px; background: var(--border); color: var(--muted);
  }}
  .rec-warning .rec-badge {{ background: rgba(245,166,35,0.15); color: {WARNING}; }}
  .rec-critical .rec-badge {{ background: rgba(239,68,68,0.15); color: {CRITICAL}; }}

  details.energy-details {{ font-size: 13px; color: var(--muted); }}
  details.energy-details summary {{ cursor: pointer; font-size: 13px; font-weight: 600; color: var(--ink); }}
  .energy-note {{ margin-top: 12px; line-height: 1.6; }}
  .empty {{ color: var(--muted); font-size: 13px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Claude Code Usage Dashboard</h1>
    <p class="sub">Generated {generated_at} &middot; {dist.count if dist else 0} sessions tracked &middot; Claude Code only (other agent CLIs filtered out)</p>
  </header>

  <div class="note">"Cost" is what your usage would cost at pay-as-you-go API rates, not a real bill &mdash; you pay a flat subscription price on Pro/Max regardless of token usage. Treat it as a relative yardstick, not money charged.</div>

  <div class="card">
    <div class="stat-row">
      <div><div class="stat-value">{total_tokens:,}</div><div class="stat-label">Total tokens</div></div>
      <div><div class="stat-value">${total_cost:,.2f}</div><div class="stat-label">Est. API cost</div></div>
      <div><div class="stat-value">{f"{latest_eff:.0%}" if latest_eff is not None else "n/a"}</div><div class="stat-label">Latest cache efficiency</div></div>
      <div><div class="stat-value">{f"{dist.median_tokens:,.0f}" if dist else "n/a"}</div><div class="stat-label">Median session tokens</div></div>
    </div>
  </div>

  <h2>Usage by period</h2>
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

  <h2>Cache efficiency (last 14 days)</h2>
  <div class="card">{_cache_efficiency_section()}</div>

  <h2>Sessions</h2>
  <div class="card">{_outliers_section()}</div>

  <h2>Recommendations</h2>
  <div class="card">{_recommendations_section(weekly_limit_usd)}</div>

  <h2>Energy (experimental)</h2>
  <div class="card">{_energy_section()}</div>
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

    OUTPUT_PATH.write_text(html)
    return OUTPUT_PATH


def generate_and_open(weekly_limit_usd: float | None = None, db_path: Path = DEFAULT_DB_PATH) -> Path:
    path = generate(weekly_limit_usd, db_path)
    webbrowser.open(f"file://{path}")
    return path
