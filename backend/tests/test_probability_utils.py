"""Tests for backend.ai.probability_utils.clamp_probability."""
from __future__ import annotations

import pytest

from backend.ai.probability_utils import clamp_probability


@pytest.mark.parametrize(
    "input_val, expected",
    [
        (0.0, 0.01),
        (1.0, 0.99),
        (-0.5, 0.01),
        (1.5, 0.99),
        (0.5, 0.5),
        (0.99, 0.99),
        (0.01, 0.01),
        (0.6, 0.6),
    ],
)
def test_clamp_default_epsilon(input_val, expected):
    assert clamp_probability(input_val) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    "input_val, epsilon, expected",
    [
        (0.0, 0.05, 0.05),
        (1.0, 0.05, 0.95),
        (0.5, 0.05, 0.5),
        (0.03, 0.05, 0.05),
        (0.97, 0.05, 0.95),
    ],
)
def test_clamp_custom_epsilon(input_val, epsilon, expected):
    assert clamp_probability(input_val, epsilon) == pytest.approx(expected, abs=1e-6)


def test_clamp_warns_on_out_of_bounds(caplog):
    with caplog.at_level("WARNING"):
        clamp_probability(0.0)
    assert "clamp_probability" in caplog.text


def test_clamp_no_warning_in_bounds(caplog):
    with caplog.at_level("WARNING"):
        clamp_probability(0.5)
    assert "clamp_probability" not in caplog.text


def test_clamp_return_type():
    result = clamp_probability(0.42)
    assert isinstance(result, float)
