"""Human-readable Track B progress lines."""

from __future__ import annotations

import logging
from typing import Final

LOGGER = logging.getLogger(__name__)

TRACK_B_PHASE_COUNT: Final[int] = 6

PHASE_FLAG = "flag_select"
PHASE_DIAGNOSE = "diagnose"
PHASE_SAMPLE = "sample_repair_sham"
PHASE_NORMALIZE = "normalize"
PHASE_ANALYZE = "analyze"
PHASE_REPORT = "report"


def _overall_percent(phase_index: int, step_done: int, step_total: int) -> float:
    if TRACK_B_PHASE_COUNT <= 0:
        return 0.0
    base = (phase_index - 1) / TRACK_B_PHASE_COUNT
    st = max(int(step_total), 1)
    within = min(1.0, max(0.0, float(step_done) / float(st))) / TRACK_B_PHASE_COUNT
    return 100.0 * min(1.0, base + within)


def log_track_b_line(
    *,
    phase_index: int,
    phase_name: str,
    step_label: str,
    step_done: int,
    step_total: int,
    detail: str = "",
) -> None:
    st = max(step_total, 1)
    step_pct = 100.0 * min(1.0, float(step_done) / float(st))
    overall = _overall_percent(phase_index, step_done, step_total)
    extra = f" | {detail}" if detail else ""
    LOGGER.info(
        "[Track B] phase %s/%s %s | %s %s/%s (%.1f%%) | overall %.1f%%%s",
        phase_index,
        TRACK_B_PHASE_COUNT,
        phase_name,
        step_label,
        min(step_done, step_total),
        step_total,
        step_pct,
        overall,
        extra,
    )

