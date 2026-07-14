"""
utils/scoring_math.py

Small, pure, fully-documented math helpers shared by the Feature Fusion
Engine and the Deterministic Scoring Engine. Kept in one place so every
"ideal band" / "weighted average" formula in the platform is implemented
(and unit-tested) exactly once.
"""

from __future__ import annotations


def band_score(
    value: float,
    ideal_min: float,
    ideal_max: float,
    floor: float,
    ceiling: float,
) -> float:
    """
    Score how close `value` is to an ideal [ideal_min, ideal_max] band.

    Returns 1.0 for any value inside the band. Outside the band, the score
    decays linearly to 0.0 at `floor` (below `ideal_min`) or `ceiling`
    (above `ideal_max`). This is the single formula used everywhere in the
    platform that scores a raw metric against a documented "healthy range"
    (e.g. words-per-minute, pitch variation, silence ratio).

    Args:
        value: The raw metric value.
        ideal_min: Lower bound of the ideal band (score == 1.0 at/above this).
        ideal_max: Upper bound of the ideal band (score == 1.0 at/below this).
        floor: Value at or below which the score is 0.0 (must be < ideal_min).
        ceiling: Value at or above which the score is 0.0 (must be > ideal_max).

    Returns:
        A score in [0.0, 1.0].
    """
    if ideal_min <= value <= ideal_max:
        return 1.0
    if value < ideal_min:
        if floor >= ideal_min:
            return 0.0
        return max(0.0, min(1.0, (value - floor) / (ideal_min - floor)))
    if ceiling <= ideal_max:
        return 0.0
    return max(0.0, min(1.0, (ceiling - value) / (ceiling - ideal_max)))


def weighted_average(components: dict[str, tuple[float | None, float]]) -> float:
    """
    Compute a weighted average over components that may be absent.

    Args:
        components: Mapping of component name -> (value, weight). A `None`
            value means that component's input material was not supplied and
            it is excluded; the remaining weights are renormalized so they
            still sum to 1.0.

    Returns:
        The weighted average in whatever scale the input values use (this
        module is scale-agnostic; callers pass 0-1 or 0-100 consistently).
        Returns 0.0 if no component has a value.
    """
    available = [(value, weight) for value, weight in components.values() if value is not None]
    total_weight = sum(weight for _value, weight in available)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in available) / total_weight


def clamp_score(value: float) -> int:
    """Clamp a 0-100 float score to an int in [0, 100]."""
    return int(round(max(0.0, min(100.0, value))))
