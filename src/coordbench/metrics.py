from __future__ import annotations

from collections import Counter
from typing import Iterable

import numpy as np


def distribution_from_answers(answers: Iterable[str]) -> dict[str, float]:
    counts = Counter(answer for answer in answers if answer)
    total = sum(counts.values())
    if total == 0:
        return {}
    return {key: value / total for key, value in counts.items()}


def top1_label(distribution: dict[str, float]) -> str:
    if not distribution:
        return ""
    return sorted(distribution.items(), key=lambda item: (-item[1], item[0]))[0][0]


def jsd(distribution_a: dict[str, float], distribution_b: dict[str, float]) -> float:
    keys = sorted(set(distribution_a) | set(distribution_b))
    if not keys:
        return 0.0
    a = np.array([distribution_a.get(key, 0.0) for key in keys], dtype=float)
    b = np.array([distribution_b.get(key, 0.0) for key in keys], dtype=float)
    midpoint = 0.5 * (a + b)

    def _kl(left: np.ndarray, right: np.ndarray) -> float:
        mask = left > 0
        return float(np.sum(left[mask] * np.log2(left[mask] / right[mask])))

    return 0.5 * _kl(a, midpoint) + 0.5 * _kl(b, midpoint)


def tvd(distribution_a: dict[str, float], distribution_b: dict[str, float]) -> float:
    keys = sorted(set(distribution_a) | set(distribution_b))
    if not keys:
        return 0.0
    return float(0.5 * sum(abs(distribution_a.get(key, 0.0) - distribution_b.get(key, 0.0)) for key in keys))


def top1_match(distribution_a: dict[str, float], distribution_b: dict[str, float]) -> int:
    return int(top1_label(distribution_a) == top1_label(distribution_b))


def focal_flip(distribution_a: dict[str, float], distribution_b: dict[str, float]) -> int:
    return 1 - top1_match(distribution_a, distribution_b)


def _average_ranks_desc(values: np.ndarray) -> np.ndarray:
    order = np.argsort(-values, kind="mergesort")
    ranks = np.zeros(len(values), dtype=float)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and np.isclose(values[order[end]], values[order[start]]):
            end += 1
        average_rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    return ranks


def spearman_frequency(distribution_a: dict[str, float], distribution_b: dict[str, float]) -> float | None:
    keys = sorted(set(distribution_a) | set(distribution_b))
    if len(keys) < 3:
        return None
    a = np.array([distribution_a.get(key, 0.0) for key in keys], dtype=float)
    b = np.array([distribution_b.get(key, 0.0) for key in keys], dtype=float)
    a_ranks = _average_ranks_desc(a)
    b_ranks = _average_ranks_desc(b)
    if np.isclose(a_ranks.std(), 0.0) or np.isclose(b_ranks.std(), 0.0):
        return None
    return float(np.corrcoef(a_ranks, b_ranks)[0, 1])
