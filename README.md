# claude-code-usage-tracker

Tracks your [Claude Code](https://claude.com/claude-code) usage over time and
suggests concrete ways to reduce it -- built on top of
[`ccusage`](https://github.com/ryoppippi/ccusage) rather than parsing Claude
Code's session logs directly.

```
=== Usage by week ===
Period       Tokens  Est. API Cost
--------  ---------  -------------
2026-W26  228209216         $80.10
2026-W27  557861734        $142.78

=== Recommendations (14) ===
!  Session b92c0ed1... on 2026-07-07 used 512,188,686 tokens (164.03x the median) — consider splitting into smaller tasks
```

## What this actually measures

`ccusage` computes "cost" from your token counts using Anthropic's
pay-as-you-go **API** rates. If you're on a flat-rate plan (Pro/Max), that's
not a real bill -- you pay the same subscription price regardless of token
usage. Treat "cost" here as a relative yardstick for how much you're using,
not money actually charged. It becomes literally accurate only if you're on
metered API billing.

`ccusage` also tracks multiple coding-agent CLIs (Claude Code, Codex,
etc.) in the same local data if you have more than one installed. This tool
filters everything down to Claude Code only before it's stored.

## Requirements

- Python 3.10+ (stdlib only -- no `pip install` needed)
- Node.js (for `npx ccusage@latest`)
- macOS, if you want the optional daily-automation script (`setup_launchd.sh`
  uses `launchd`; on Linux, a cron entry calling `python3 cli.py sync` does
  the same job)

## Setup

```bash
git clone <this repo>
cd claude-code-usage-tracker
python3 cli.py sync      # pulls your Claude Code history into usage.db
python3 cli.py report    # see it
```

That's it -- no dependencies to install, no config file required.

### Optional: run it automatically (macOS)

```bash
./setup_launchd.sh
```

Installs a `launchd` job that runs `sync` daily at 8pm plus once
immediately, so `usage.db` builds history without you remembering to run
anything. Uninstall instructions are printed after it runs.

### Optional: quick aliases

Add to your `~/.zshrc` (adjust the path):

```bash
alias ccreport='python3 /path/to/claude-code-usage-tracker/cli.py report'
alias ccreport-week='python3 /path/to/claude-code-usage-tracker/cli.py report --granularity week'
alias ccsync='python3 /path/to/claude-code-usage-tracker/cli.py sync'
```

## Usage

```bash
python3 cli.py sync                          # fetch + snapshot latest data
python3 cli.py report                        # daily view
python3 cli.py report --granularity week     # or month
python3 cli.py report --weekly-limit 150     # turn on the budget-alarm rule
python3 cli.py report --energy               # rough energy-use estimate (see below)
```

`sync` is idempotent (safe to run as often as you like -- re-running it
updates today's/any in-progress session's numbers in place rather than
duplicating rows).

## How it works

1. **`fetch.py`** -- shells out to `npx ccusage@latest daily/session --json`,
   filters the result to Claude Code only. (A single day's `ccusage` entry
   can be a *mix* of agents summed together, so daily filtering recomputes
   totals from `modelBreakdowns` rather than just dropping mixed rows;
   session-level filtering is simpler since a session belongs to exactly one
   agent.)
2. **`snapshot.py`** -- upserts fetched records into a local SQLite
   `usage.db`. This is what gives you *history* -- `ccusage` itself only
   ever reports current logs, nothing persists across runs on its own.
3. **`metrics.py`** -- token/cost aggregates by day/week/month, cache
   efficiency (`cache_read / (cache_read + cache_creation)`) trended daily
   and per-session, session token distribution and outlier detection.
4. **`strategy.py`** -- a small list of rule functions evaluated against
   those metrics, each producing a plain-language recommendation. Adding a
   rule is just adding a function with the same shape.
5. **`cli.py`** -- ties it together into `sync`/`report` subcommands.
6. **`energy.py`** (opt-in via `--energy`) -- a rough energy-use estimate.
   Anthropic doesn't disclose Claude's architecture or hardware, so there's
   no way to compute a real Claude-specific figure -- this applies a
   joules-per-output-token rate from published research on *other* models
   to your output token counts, as an order-of-magnitude proxy. Shows a
   low/mid/high range (0.39-7.2 J/token, an ~18x spread across measured
   hardware/model sizes) rather than a single falsely-precise number.
   Deliberately excludes input/cache tokens from the estimate, since the
   source research found prefill is <=3.4% of real inference energy versus
   >=96% for decode (output generation). Sources:
   - Luccioni, Jernite & Strubell, ["Power Hungry Processing: Watts Driving
     the Cost of AI Deployment?"](https://arxiv.org/abs/2311.16863),
     ACM FAccT 2024.
   - ["Where Do the Joules Go? Diagnosing Inference Energy
     Consumption"](https://arxiv.org/pdf/2601.22076) (2026).
   - ["Beyond Test-Time Compute Strategies: Advocating Energy-per-Token in
     LLM Inference"](https://arxiv.org/pdf/2603.20224).
   - [TokenPowerBench: Benchmarking the Power Consumption of LLM
     Inference](https://arxiv.org/html/2512.03024v1).

## What ccusage doesn't expose

- **No per-project breakdown.** Checked both the JSON output and `--help`
  for `daily`/`session` -- there's no `project` field or flag. If you want
  this, it'd need a different data source entirely.
- **No real account/plan limit.** Claude Code's actual rate limit runs on
  rolling 5-hour session blocks (`npx ccusage@latest blocks --active`
  shows the live one), not a simple weekly cap -- and neither `ccusage` nor
  this tool can see your actual plan entitlement anyway. The
  `--weekly-limit` flag is a **self-chosen** budget alarm, not Anthropic's
  technical limit.

## License

MIT
