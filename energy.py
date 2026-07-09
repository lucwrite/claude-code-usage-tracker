"""Rough energy estimation -- NOT part of the spec's original build order,
added on request as an experimental extra.

This is fundamentally a proxy estimate, not a measurement: Anthropic
doesn't disclose Claude's architecture, hardware, or serving setup, so
there is no way to compute a Claude-specific number. Every figure here
is derived from published, peer-reviewed/preprint research measuring
OTHER (open) models, applied to your token counts as a rough stand-in.
Treat the output as "roughly this order of magnitude," not a bill.

Sources (see README for full citations):
  - Luccioni, Jernite & Strubell, "Power Hungry Processing: Watts Driving
    the Cost of AI Deployment?", ACM FAccT 2024. https://arxiv.org/abs/2311.16863
  - "Where Do the Joules Go? Diagnosing Inference Energy Consumption"
    (2026), which found prefill (input tokens) is <=3.4% of total
    inference energy, decode (output tokens) is >=96%.
  - Measured joules/output-token range across recent papers spans
    roughly 0.39 J/token (LLaMA3-70B, H100, FP8 -- efficient modern
    serving) to 7.2 J/token (older/larger models, less optimized
    serving) -- almost a 10x spread from hardware/optimization choices
    alone. LOW/MID/HIGH below are anchored to that measured range, not
    invented.

Because input/cache tokens are a small fraction of real energy cost per
the "Where Do the Joules Go?" finding, this deliberately does NOT apply
the per-token rate to input_tokens, cache_read_tokens, or
cache_creation_tokens -- doing so would substantially overstate energy
use for the (very common) case of a cache-heavy session.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metrics import PeriodUsage, tokens_by_period
from snapshot import DEFAULT_DB_PATH

JOULES_PER_WH = 3600.0

# Joules per OUTPUT token. Anchored to the measured range in recent
# benchmarking papers (see module docstring) -- not Claude-specific.
LOW_J_PER_OUTPUT_TOKEN = 0.39
MID_J_PER_OUTPUT_TOKEN = 2.0
HIGH_J_PER_OUTPUT_TOKEN = 7.2

# Everyday-comparison reference points, both commonly-used rough figures
# in energy communication -- not precise, just for intuition.
SMARTPHONE_CHARGE_WH = 15.0
LED_BULB_WATTS = 10.0  # a 10W LED bulb; Wh / 10 = hours of runtime


@dataclass
class EnergyEstimate:
    period: str
    output_tokens: int
    low_wh: float
    mid_wh: float
    high_wh: float


def _tokens_to_wh(output_tokens: int, j_per_token: float) -> float:
    return (output_tokens * j_per_token) / JOULES_PER_WH


def estimate_for_output_tokens(output_tokens: int) -> tuple[float, float, float]:
    """Returns (low_wh, mid_wh, high_wh) for a raw output-token count."""
    return (
        _tokens_to_wh(output_tokens, LOW_J_PER_OUTPUT_TOKEN),
        _tokens_to_wh(output_tokens, MID_J_PER_OUTPUT_TOKEN),
        _tokens_to_wh(output_tokens, HIGH_J_PER_OUTPUT_TOKEN),
    )


def energy_by_period(granularity: str = "day", db_path: Path = DEFAULT_DB_PATH) -> list[EnergyEstimate]:
    out = []
    for p in tokens_by_period(granularity, db_path):
        low, mid, high = estimate_for_output_tokens(p.output_tokens)
        out.append(EnergyEstimate(period=p.period, output_tokens=p.output_tokens, low_wh=low, mid_wh=mid, high_wh=high))
    return out


def total_energy(periods: list[PeriodUsage]) -> tuple[float, float, float]:
    """Aggregate (low_wh, mid_wh, high_wh) across a list of PeriodUsage."""
    total_output = sum(p.output_tokens for p in periods)
    return estimate_for_output_tokens(total_output)


def relatable_comparison(wh: float) -> str:
    charges = wh / SMARTPHONE_CHARGE_WH
    bulb_hours = wh / LED_BULB_WATTS
    return f"~{charges:.1f} smartphone charges, or a 10W LED bulb running ~{bulb_hours:.1f} hours"
