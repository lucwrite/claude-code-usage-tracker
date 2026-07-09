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
METHODOLOGY_FILENAME = "methodology.html"
METHODOLOGY_OUTPUT_PATH = Path(__file__).parent / METHODOLOGY_FILENAME

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
    not a precise number. <a href="{METHODOLOGY_FILENAME}">Exactly how this is calculated, and the sources
    it's drawn from &rarr;</a></p>'''


def generate_methodology(output_path: Path = METHODOLOGY_OUTPUT_PATH) -> Path:
    """A static writeup of the energy-estimate methodology and its sources.
    Content here is fixed (not derived from usage_snapshots), so unlike
    generate() there's no data to thread through -- it's regenerated
    every time generate() runs purely to guarantee it always exists as a
    sibling of report.html wherever that gets published, in sync with
    whatever the current constants/logic in energy.py actually are."""
    low_wh_per_1k, mid_wh_per_1k, high_wh_per_1k = estimate_for_output_tokens(1000)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>How the energy estimate works</title>
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
  .wrap {{ max-width: 700px; margin: 0 auto; padding: 36px 24px 70px; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .back {{ display: inline-block; font-size: 13px; margin-bottom: 22px; }}
  h1 {{ font-size: 24px; margin: 0 0 6px; }}
  .sub {{ color: var(--muted); font-size: 13px; margin: 0 0 32px; line-height: 1.6; }}
  h2 {{ font-size: 15px; margin: 34px 0 12px; color: var(--ink); }}
  p, li {{ font-size: 14.5px; line-height: 1.7; color: var(--ink); }}
  p.muted {{ color: var(--muted); font-size: 13.5px; }}
  .card {{ background: var(--paper); border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px; margin: 14px 0; }}
  code {{ background: #0b0d11; border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 10px 0; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em; }}
  td.num {{ font-variant-numeric: tabular-nums; }}
  ol.sources {{ padding-left: 20px; }}
  ol.sources li {{ margin-bottom: 14px; }}
  .caveat {{ border-left: 3px solid {WARNING}; background: rgba(245,166,35,0.08); border-radius: 8px; padding: 14px 16px; margin: 20px 0; }}
  .caveat p {{ margin: 0; }}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="report.html">&larr; Back to dashboard</a>
  <h1>How the energy estimate works</h1>
  <p class="sub">This page exists because "roughly this many Wh" deserves to show its work. Everything below
  is exactly what the code does &mdash; no rounding of the explanation to make it sound more precise than it is.</p>

  <div class="caveat">
    <p><strong>The short version:</strong> Anthropic doesn't publish Claude's model architecture, hardware, or
    serving setup, so there is no way for anyone outside Anthropic to compute a real Claude-specific
    energy figure. Every number on the dashboard's Energy estimate section is a proxy: measurements from
    published research on <em>other</em>, openly-benchmarked models, applied to your own token counts as an
    order-of-magnitude stand-in. Treat it as "roughly this ballpark," never as a bill.</p>
  </div>

  <h2>1. Where the underlying usage numbers come from</h2>
  <p>Token counts and cost figures come from <code>ccusage</code>, a local CLI that reads Claude Code's own
  session logs on your machine &mdash; nothing is scraped from Anthropic's servers, and nothing about the
  content of your conversations is read, only the token/cost metadata each session already records. This
  tool snapshots that output into a local SQLite database each time you run <code>sync</code>, which is what
  lets it show trends over time even though <code>ccusage</code> itself is stateless.</p>

  <h2>2. Why the estimate uses output tokens only</h2>
  <p>A request to an LLM has two phases: <strong>prefill</strong> (processing what you and any reused context
  send in) and <strong>decode</strong> (generating the reply, one token at a time). These cost very
  different amounts of energy. The paper "Where Do the Joules Go? Diagnosing Inference Energy Consumption"
  measured prefill at <strong>&le;3.4%</strong> of total inference energy and decode at <strong>&ge;96%</strong>
  &mdash; generating output dominates. That's why this tool's estimate is driven entirely by
  <code>output_tokens</code> and deliberately ignores <code>input_tokens</code>, <code>cache_read_tokens</code>,
  and <code>cache_creation_tokens</code>. Applying the same per-token rate to those would substantially
  overstate energy use, especially for the very common case of a cache-heavy session (context Claude reused
  instead of reprocessing costs close to nothing by comparison).</p>

  <h2>3. The joules-per-token rate</h2>
  <p>Recent benchmarking papers report measured energy per output token ranging roughly
  <strong>0.39 J/token</strong> (e.g. LLaMA3-70B on an H100 in FP8 &mdash; efficient, modern serving) up to
  <strong>7.2 J/token</strong> (older or larger models, less optimized serving) &mdash; almost a 20x spread
  driven purely by hardware and serving choices. Rather than pick one number and imply false precision, this
  tool anchors a low/mid/high range directly to that measured spread:</p>

  <div class="card">
    <table>
      <tr><th>Estimate</th><th>Joules / output token</th><th>Wh per 1,000 output tokens</th></tr>
      <tr><td>Low</td><td class="num">0.39 J</td><td class="num">{low_wh_per_1k:.3f} Wh</td></tr>
      <tr><td>Mid</td><td class="num">2.0 J</td><td class="num">{mid_wh_per_1k:.3f} Wh</td></tr>
      <tr><td>High</td><td class="num">7.2 J</td><td class="num">{high_wh_per_1k:.3f} Wh</td></tr>
    </table>
  </div>

  <p>The conversion from joules to the watt-hours (Wh) shown on the dashboard is just unit conversion:</p>
  <div class="card"><p style="margin:0;"><code>Wh = (output_tokens &times; joules_per_token) / 3600</code></p></div>
  <p class="muted">3600 is simply the number of joules in one watt-hour &mdash; there's no research judgment
  in that step, it's a fixed physical conversion.</p>

  <h2>4. How this rolls up into what you see on the dashboard</h2>
  <p>Every energy figure on the dashboard &mdash; the per-day/week/month "~X Wh" next to each usage bar, the
  "typical conversation" vs. "your longest conversation" comparison, the per-outlier Wh next to each
  unusually-long conversation, and the running lifetime low/mid/high total &mdash; all call the exact same
  function on a different slice of your <code>output_tokens</code>: one conversation's worth, one day's
  worth, or everything ever tracked. There's a single code path, just applied at different granularities, so
  the numbers stay internally consistent with each other.</p>
  <p>The "smartphone charges" and "10W LED bulb hours" comparisons are separate, commonly-used rough
  reference points for energy communication (a phone charge &asymp; 15 Wh; a 10W bulb uses 10 Wh per hour)
  &mdash; included only for intuition, not as another research-derived figure.</p>

  <h2>5. Sources</h2>
  <ol class="sources">
    <li>Luccioni, A., Jernite, Y., &amp; Strubell, E. (2024).
      <a href="https://arxiv.org/abs/2311.16863" target="_blank" rel="noopener">"Power Hungry Processing:
      Watts Driving the Cost of AI Deployment?"</a> ACM Conference on Fairness, Accountability, and
      Transparency (FAccT 2024). Peer-reviewed measurement of real-world inference energy costs across
      open models &mdash; the source for the general "generation costs far more than input processing"
      finding this tool relies on.</li>
    <li>"Where Do the Joules Go? Diagnosing Inference Energy Consumption" (2026).
      <a href="https://arxiv.org/pdf/2601.22076" target="_blank" rel="noopener">arXiv:2601.22076</a>.
      The specific &le;3.4% prefill / &ge;96% decode split cited above comes from this paper.</li>
    <li>"Beyond Test-Time Compute Strategies: Advocating Energy-per-Token in LLM Inference."
      <a href="https://arxiv.org/pdf/2603.20224" target="_blank" rel="noopener">arXiv:2603.20224</a>.
      Contributes to the measured joules-per-output-token range this tool's low/mid/high constants are
      anchored to.</li>
    <li>"TokenPowerBench: Benchmarking the Power Consumption of LLM Inference."
      <a href="https://arxiv.org/html/2512.03024v1" target="_blank" rel="noopener">arXiv:2512.03024</a>.
      Benchmark data across model sizes/hardware, also feeding the low/mid/high spread.</li>
  </ol>

  <h2>6. What this deliberately is not</h2>
  <ul>
    <li><strong>Not Claude-specific.</strong> None of the source papers benchmark Claude itself &mdash;
    Anthropic hasn't published the figures that would make that possible. This is the best available proxy,
    not a measurement of Anthropic's actual infrastructure.</li>
    <li><strong>Not a bill.</strong> Nothing here corresponds to money, carbon offsets, or any number
    Anthropic reports. It's a rough physical-energy estimate only.</li>
    <li><strong>Not per-conversation ground truth.</strong> Real energy use depends on hardware, batching,
    data-center efficiency (PUE), and cooling &mdash; none of which are knowable from the outside. The
    low/mid/high range exists specifically so a single number doesn't get mistaken for a precise one.</li>
  </ul>

  <p class="muted" style="margin-top:36px;">Source code for this whole tool, including <code>energy.py</code>
  where these constants live, is open on GitHub:
  <a href="https://github.com/lucwrite/claude-code-usage-tracker" target="_blank" rel="noopener">lucwrite/claude-code-usage-tracker</a>.</p>
</div>
</body>
</html>
'''

    output_path.write_text(html)
    return output_path


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
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
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
    generate_methodology(output_path.parent / METHODOLOGY_FILENAME)
    return output_path


def generate_and_open(weekly_limit_usd: float | None = None, db_path: Path = DEFAULT_DB_PATH) -> Path:
    path = generate(weekly_limit_usd, db_path)
    webbrowser.open(f"file://{path}")
    return path
