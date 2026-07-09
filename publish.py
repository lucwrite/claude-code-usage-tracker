"""Publishes the dashboard to the hosted Vercel wrapper (~/claude-usage-dashboard).

That project is a thin Next.js app whose only job is to serve whatever
HTML file sits in its public/ folder -- publicly accessible, no
password (removed on request; the data here was assessed as low-
sensitivity: usage volume/cost/timing, never conversation content).
This module writes the freshly-generated dashboard there and
(optionally) triggers a production deploy -- ccusage itself only reads
local session logs, so there's no way for a hosted server to fetch this
data on its own; publishing is how a snapshot gets there.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from snapshot import DEFAULT_DB_PATH
from web import generate

HOSTED_PROJECT_DIR = Path.home() / "claude-usage-dashboard"
HOSTED_DATA_PATH = HOSTED_PROJECT_DIR / "public" / "report.html"


class PublishError(Exception):
    pass


def publish(weekly_limit_usd: float | None = None, db_path: Path = DEFAULT_DB_PATH, deploy: bool = True) -> Path:
    if not HOSTED_PROJECT_DIR.exists():
        raise PublishError(
            f"{HOSTED_PROJECT_DIR} doesn't exist -- the hosted wrapper project must be set up first."
        )
    HOSTED_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        generate(weekly_limit_usd=weekly_limit_usd, db_path=db_path, output_path=HOSTED_DATA_PATH)
    except Exception as e:
        raise PublishError(f"failed to generate the dashboard: {e}") from e

    if not deploy:
        return HOSTED_DATA_PATH

    try:
        subprocess.run(
            ["npx", "vercel", "--prod", "--yes"],
            cwd=HOSTED_PROJECT_DIR,
            capture_output=True, text=True, timeout=180, check=True,
        )
    except FileNotFoundError as e:
        raise PublishError("npx not found on PATH -- is Node.js installed?") from e
    except subprocess.CalledProcessError as e:
        raise PublishError(f"vercel deploy failed: {e.stderr.strip()}") from e
    except subprocess.TimeoutExpired as e:
        raise PublishError("vercel deploy timed out after 180s") from e

    return HOSTED_DATA_PATH
