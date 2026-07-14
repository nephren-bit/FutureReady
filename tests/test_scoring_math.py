"""Unit tests for utils/scoring_math.py — the shared band_score / weighted_average helpers."""

from __future__ import annotations

from utils.scoring_math import band_score, clamp_score, weighted_average


class TestBandScore:
    def test_inside_ideal_band_returns_one(self) -> None:
        assert band_score(100, 90, 110, 0, 200) == 1.0

    def test_at_floor_returns_zero(self) -> None:
        assert band_score(0, 90, 110, 0, 200) == 0.0

    def test_at_ceiling_returns_zero(self) -> None:
        assert band_score(200, 90, 110, 0, 200) == 0.0

    def test_below_band_decays_linearly(self) -> None:
        # Halfway between floor (0) and ideal_min (100) -> 0.5
        assert band_score(50, 100, 150, 0, 300) == 0.5

    def test_above_band_decays_linearly(self) -> None:
        # Halfway between ideal_max (150) and ceiling (300) -> 0.5
        assert band_score(225, 100, 150, 0, 300) == 0.5

    def test_result_always_bounded(self) -> None:
        for value in (-1000, -1, 0, 50, 100, 1000):
            score = band_score(value, 40, 60, 0, 100)
            assert 0.0 <= score <= 1.0


class TestWeightedAverage:
    def test_all_present(self) -> None:
        result = weighted_average({"a": (1.0, 0.5), "b": (0.0, 0.5)})
        assert result == 0.5

    def test_missing_component_is_renormalized(self) -> None:
        # Only "a" present with weight 0.5 out of a nominal 1.0 total -> its
        # value alone should determine the result once renormalized.
        result = weighted_average({"a": (1.0, 0.5), "b": (None, 0.5)})
        assert result == 1.0

    def test_all_missing_returns_zero(self) -> None:
        assert weighted_average({"a": (None, 0.5), "b": (None, 0.5)}) == 0.0

    def test_empty_returns_zero(self) -> None:
        assert weighted_average({}) == 0.0


class TestClampScore:
    def test_clamps_above_hundred(self) -> None:
        assert clamp_score(150.0) == 100

    def test_clamps_below_zero(self) -> None:
        assert clamp_score(-10.0) == 0

    def test_rounds_to_nearest_int(self) -> None:
        assert clamp_score(72.6) == 73
