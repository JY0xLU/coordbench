import pytest

from coordbench.metrics import focal_flip, jsd, spearman_frequency, top1_match, tvd


def test_distribution_metrics_basic():
    left = {"london": 0.75, "paris": 0.25}
    right = {"london": 0.50, "paris": 0.50}

    assert jsd(left, right) > 0
    assert tvd(left, right) == 0.25
    assert top1_match(left, right) == 1
    assert focal_flip(left, right) == 0


def test_spearman_requires_enough_support():
    left = {"a": 0.7, "b": 0.2, "c": 0.1}
    right = {"a": 0.2, "b": 0.5, "c": 0.3}
    assert spearman_frequency(left, right) is not None


def test_spearman_handles_ties_with_average_ranks():
    left = {"a": 0.4, "b": 0.4, "c": 0.2}
    right = {"a": 0.4, "b": 0.2, "c": 0.4}

    assert spearman_frequency(left, right) == pytest.approx(-0.5)
