"""Feature-based similarity between two products of the same category.

Score is 0..1. Each category has weighted features; some are "hard" (a tire of a
different size is not a substitute no matter how alike the titles are), and a
hard mismatch caps the score. Same GTIN or manufacturer part number means the
same item sold by another retailer, which scores 1.0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import FeatureComparison


@dataclass(frozen=True)
class Rule:
    feature: str
    weight: float
    hard: bool = False
    numeric_tolerance: float | None = None  # relative tolerance for numbers


RULES: dict[str, list[Rule]] = {
    "tire": [
        Rule("tire_size", 5, hard=True),
        Rule("season", 2),
        Rule("load_index", 1.5),
        Rule("speed_rating", 1.5),
        Rule("tire_type", 1),
        Rule("run_flat", 1, hard=True),
        Rule("treadwear_warranty_miles", 0.5, numeric_tolerance=0.15),
    ],
    "motor_oil": [
        Rule("viscosity", 5, hard=True),
        Rule("oil_type", 3),
        Rule("engine", 1),
        Rule("approvals", 1),
    ],
    "battery": [
        Rule("group_size", 5, hard=True),
        Rule("voltage", 2, hard=True),
        Rule("chemistry", 2),
        Rule("cca", 2, numeric_tolerance=0.1),
        Rule("reserve_capacity_min", 1, numeric_tolerance=0.15),
        Rule("warranty_years", 0.5, numeric_tolerance=0.34),
    ],
    "wiper_blade": [Rule("blade_length_in", 5, hard=True), Rule("blade_style", 1.5)],
    "brake_pads": [Rule("position", 3, hard=True), Rule("pad_material", 2)],
    "headlight_bulb": [
        Rule("bulb_code", 5, hard=True),
        Rule("bulb_tech", 2),
        Rule("color_temp_k", 0.5, numeric_tolerance=0.1),
        Rule("lumens", 0.5, numeric_tolerance=0.25),
    ],
    "spark_plug": [Rule("electrode", 2)],
    "coolant": [Rule("mix", 3, hard=True), Rule("spec", 1)],
    "transmission_fluid": [Rule("spec", 4, hard=True)],
    "brake_fluid": [Rule("dot_rating", 5, hard=True)],
}

COMMON_RULES = [
    Rule("fits_makes", 1.5),
    Rule("fits_years", 1.5),
    Rule("pack_count", 1, numeric_tolerance=0.0),
]
# Brand is deliberately not compared: a different brand with the same spec is
# exactly the substitute a price comparison is looking for.

TITLE_WEIGHT = 1.5
HARD_MISMATCH_CAP = 0.25
_STOP = {"the", "and", "for", "with", "of", "a", "in", "to", "by", "pack", "new", "-", "&"}


def _tokens(title: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9/.-]+", title.lower()) if t not in _STOP and len(t) > 1}


def title_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def _compare(rule: Rule, a: Any, b: Any) -> float:
    """Similarity 0..1 for one feature where both sides are present."""
    if rule.feature == "fits_years":
        (a0, a1), (b0, b1) = a, b
        return 1.0 if max(a0, b0) <= min(a1, b1) else 0.0
    if isinstance(a, list) or isinstance(b, list):
        sa = set(_norm(a if isinstance(a, list) else [a]))
        sb = set(_norm(b if isinstance(b, list) else [b]))
        return 1.0 if sa & sb else 0.0
    if rule.numeric_tolerance is not None:
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            return 1.0 if _norm(a) == _norm(b) else 0.0
        if fa == fb:
            return 1.0
        rel = abs(fa - fb) / max(abs(fa), abs(fb))
        if rel <= rule.numeric_tolerance:
            return 1.0
        return max(0.0, 1.0 - rel / 0.5)
    return 1.0 if _norm(a) == _norm(b) else 0.0


def same_item(a: dict[str, Any], b: dict[str, Any]) -> bool:
    for key in ("gtin", "part_number"):
        va, vb = a.get(key), b.get(key)
        if va and vb and str(va).lower().lstrip("0") == str(vb).lower().lstrip("0"):
            return True
    return False


def similarity(
    category_a: str,
    features_a: dict[str, Any],
    title_a: str,
    category_b: str,
    features_b: dict[str, Any],
    title_b: str,
) -> tuple[float, list[FeatureComparison]]:
    if category_a != category_b:
        return 0.0, []

    comparisons: list[FeatureComparison] = []
    if same_item(features_a, features_b):
        for key in ("gtin", "part_number"):
            if features_a.get(key) and features_b.get(key):
                comparisons.append(FeatureComparison(feature=key, a=features_a[key], b=features_b[key], match=True))
        return 1.0, comparisons

    earned = 0.0
    possible = 0.0
    hard_mismatch = False
    for rule in RULES.get(category_a, []) + COMMON_RULES:
        va, vb = features_a.get(rule.feature), features_b.get(rule.feature)
        if va is None and vb is None:
            continue
        if va is None or vb is None:
            # Unknown on one side: count half the weight against the score.
            possible += rule.weight / 2
            continue
        score = _compare(rule, va, vb)
        earned += score * rule.weight
        possible += rule.weight
        comparisons.append(FeatureComparison(feature=rule.feature, a=va, b=vb, match=score >= 0.99))
        if rule.hard and score < 0.99:
            hard_mismatch = True

    earned += title_similarity(title_a, title_b) * TITLE_WEIGHT
    possible += TITLE_WEIGHT

    total = earned / possible if possible else 0.0
    if hard_mismatch:
        total = min(total, HARD_MISMATCH_CAP)
    return round(total, 3), comparisons
