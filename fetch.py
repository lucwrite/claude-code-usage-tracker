"""Fetch/parse wrapper around `ccusage --json`.

Responsible for: shelling out to ccusage, parsing its JSON, and filtering
the result down to Claude Code usage only. ccusage tracks multiple local
coding-agent CLIs (Claude Code, Codex, etc.) in the same output, so a day
or session that also used another tool needs its Claude-only figures
recomputed from modelBreakdowns rather than taken at face value — see
CLAUDE_MODEL_PREFIX below.

Does not touch SQLite — that's the snapshot layer (step 3).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field

CCUSAGE_CMD = ["npx", "ccusage@latest"]
CLAUDE_MODEL_PREFIX = "claude"
CLAUDE_AGENT_NAME = "claude"


class CcusageError(Exception):
    """Raised when ccusage can't be run or its output can't be parsed."""


@dataclass
class DailyUsage:
    date: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    total_tokens: int
    models_used: list[str] = field(default_factory=list)


@dataclass
class SessionUsage:
    session_id: str
    date: str  # derived from metadata.lastActivity, not a native ccusage field
    last_activity: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    total_tokens: int
    models_used: list[str] = field(default_factory=list)


def _run_ccusage(*args: str) -> dict:
    cmd = [*CCUSAGE_CMD, *args, "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    except FileNotFoundError as e:
        raise CcusageError("npx not found on PATH — is Node.js installed?") from e
    except subprocess.CalledProcessError as e:
        raise CcusageError(f"ccusage exited {e.returncode}: {e.stderr.strip()}") from e
    except subprocess.TimeoutExpired as e:
        raise CcusageError("ccusage timed out after 60s") from e

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise CcusageError(f"ccusage returned invalid JSON: {e}") from e


def _claude_model_breakdowns(entry: dict) -> list[dict]:
    return [m for m in entry.get("modelBreakdowns", []) if m.get("modelName", "").startswith(CLAUDE_MODEL_PREFIX)]


def _sum_claude_only(breakdowns: list[dict]) -> dict:
    return {
        "input_tokens": sum(m["inputTokens"] for m in breakdowns),
        "output_tokens": sum(m["outputTokens"] for m in breakdowns),
        "cache_read_tokens": sum(m["cacheReadTokens"] for m in breakdowns),
        "cache_creation_tokens": sum(m["cacheCreationTokens"] for m in breakdowns),
        "cost_usd": sum(m["cost"] for m in breakdowns),
    }


def _date_from_iso(timestamp: str) -> str:
    return timestamp.split("T", 1)[0]


def fetch_daily(since: str | None = None, until: str | None = None) -> list[DailyUsage]:
    """Claude-Code-only daily usage. Days with no Claude activity are dropped."""
    args = ["daily"]
    if since:
        args += ["--since", since]
    if until:
        args += ["--until", until]

    raw = _run_ccusage(*args)
    results: list[DailyUsage] = []
    missing_breakdowns_field = sum(1 for entry in raw["daily"] if "modelBreakdowns" not in entry)

    for entry in raw["daily"]:
        claude_breakdowns = _claude_model_breakdowns(entry)
        if not claude_breakdowns:
            continue  # this day had only non-Claude agent activity

        try:
            sums = _sum_claude_only(claude_breakdowns)
            results.append(
                DailyUsage(
                    date=entry["period"],
                    total_tokens=sums["input_tokens"]
                    + sums["output_tokens"]
                    + sums["cache_read_tokens"]
                    + sums["cache_creation_tokens"],
                    models_used=[m["modelName"] for m in claude_breakdowns],
                    **sums,
                )
            )
        except KeyError as e:
            raise CcusageError(
                f"ccusage daily output is missing an expected field ({e}) -- "
                f"its JSON shape may have changed since this tool was built"
            ) from e

    if missing_breakdowns_field:
        plural = "y" if missing_breakdowns_field == 1 else "ies"
        print(
            f"Warning: {missing_breakdowns_field} daily entr{plural} had no 'modelBreakdowns' field at all "
            f"-- ccusage's output shape may have changed; Claude Code usage may be silently missing "
            f"from this sync.",
            file=sys.stderr,
        )

    return results


def fetch_sessions(since: str | None = None, until: str | None = None) -> list[SessionUsage]:
    """Claude-Code-only sessions. A session belongs to exactly one agent in
    ccusage's output, so this filters on the top-level `agent` field rather
    than recomputing from modelBreakdowns (unlike fetch_daily, where a
    single day's entry can already be a Claude+other-agent mix)."""
    args = ["session"]
    if since:
        args += ["--since", since]
    if until:
        args += ["--until", until]

    raw = _run_ccusage(*args)
    results: list[SessionUsage] = []
    missing_agent_field = 0

    for entry in raw["session"]:
        if "agent" not in entry:
            # Distinct from "agent present but not claude" (a normal,
            # expected case for Codex/other-tool sessions) -- a genuinely
            # absent field is a stronger signal ccusage's shape changed.
            missing_agent_field += 1
            continue
        if entry["agent"] != CLAUDE_AGENT_NAME:
            continue

        try:
            last_activity = entry["metadata"]["lastActivity"]
            results.append(
                SessionUsage(
                    session_id=entry["period"],
                    date=_date_from_iso(last_activity),
                    last_activity=last_activity,
                    input_tokens=entry["inputTokens"],
                    output_tokens=entry["outputTokens"],
                    cache_read_tokens=entry["cacheReadTokens"],
                    cache_creation_tokens=entry["cacheCreationTokens"],
                    cost_usd=entry["totalCost"],
                    total_tokens=entry["totalTokens"],
                    models_used=entry.get("modelsUsed", []),
                )
            )
        except KeyError as e:
            raise CcusageError(
                f"ccusage session output is missing an expected field ({e}) -- "
                f"its JSON shape may have changed since this tool was built"
            ) from e

    if missing_agent_field:
        plural = "y" if missing_agent_field == 1 else "ies"
        print(
            f"Warning: {missing_agent_field} session entr{plural} had no 'agent' field at all "
            f"(not just a non-Claude one) -- ccusage's output shape may have changed; "
            f"Claude Code sessions may be silently missing from this sync.",
            file=sys.stderr,
        )

    return results
