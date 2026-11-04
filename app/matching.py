"""Score how well a found product matches the reference product (0..1).

Each category has weighted attributes; "hard" ones (tire size, ball size, oil
viscosity, weight rating...) cap the score when they differ, because the item
then isn't a real substitute. Attributes not listed for a category are still
compared with a default weight, so any product type works. Search results
usually only have a title, so an attribute missing on the found product costs
a little, not a lot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .extract.attributes import display_value, label


@dataclass(frozen=True)
class Rule:
    feature: str
    weight: float
    hard: bool = False
    tolerance: float | None = None  # relative tolerance for numbers


TOWING_COMMON = [
    Rule("weight_rating_lb", 4, hard=True, tolerance=0.1),
    Rule("tongue_weight_lb", 2, tolerance=0.15),
    Rule("ball_diameter_in", 3, hard=True, tolerance=0.01),
    Rule("receiver_size_in", 2, hard=True, tolerance=0.01),
    Rule("class", 1.5),
]

RULES: dict[str, list[Rule]] = {
    "weight_distribution_hitch": TOWING_COMMON + [
        Rule("sway_control", 2.5),
        Rule("bar_type", 1.5),
        Rule("shank_included", 1),
        Rule("ball_included", 0.5),
    ],
    "sway_control_kit": [Rule("weight_rating_lb", 3, tolerance=0.15), Rule("ball_diameter_in", 2, hard=True, tolerance=0.01)],
    "hitch_ball": [Rule("ball_diameter_in", 5, hard=True, tolerance=0.01), Rule("weight_rating_lb", 3, tolerance=0.15),
                   Rule("diameter_in", 2, tolerance=0.02), Rule("material", 0.5)],
    "ball_mount": TOWING_COMMON + [Rule("drop_in", 2, tolerance=0.15)],
    "receiver_hitch": [Rule("class", 4, hard=True), Rule("receiver_size_in", 3, hard=True, tolerance=0.01),
                       Rule("weight_rating_lb", 2, tolerance=0.15), Rule("tongue_weight_lb", 1, tolerance=0.2)],
    "trailer_coupler": [Rule("ball_diameter_in", 5, hard=True, tolerance=0.01), Rule("weight_rating_lb", 3, tolerance=0.15)],
    "tongue_jack": [Rule("weight_rating_lb", 4, tolerance=0.15)],
    "tire": [
        Rule("tire_size", 5, hard=True), Rule("season", 2), Rule("load_index", 1.5), Rule("speed_rating", 1.5),
        Rule("tire_type", 1), Rule("run_flat", 1, hard=True), Rule("treadwear_warranty_miles", 0.5, tolerance=0.15),
    ],
    "motor_oil": [Rule("viscosity", 5, hard=True), Rule("oil_type", 3), Rule("engine", 1), Rule("approvals", 1),
                  Rule("volume_quarts", 1, tolerance=0.05)],
    "battery": [
        Rule("group_size", 5, hard=True), Rule("voltage", 2, hard=True), Rule("chemistry", 2),
        Rule("cca", 2, tolerance=0.1), Rule("reserve_capacity_min", 1, tolerance=0.15), Rule("warranty_years", 0.5, tolerance=0.34),
    ],
    "wiper_blade": [Rule("blade_length_in", 5, hard=True), Rule("blade_style", 1.5)],
    "brake_pads": [Rule("position", 3, hard=True), Rule("pad_material", 2)],
    "headlight_bulb": [Rule("bulb_code", 5, hard=True), Rule("bulb_tech", 2), Rule("color_temp_k", 0.5, tolerance=0.1),
                       Rule("lumens", 0.5, tolerance=0.25)],
    "spark_plug": [Rule("electrode", 2)],
    "coolant": [Rule("mix", 3, hard=True), Rule("spec", 1)],
    "transmission_fluid": [Rule("spec", 4, hard=True)],
    "brake_fluid": [Rule("dot_rating", 5, hard=True)],
}

COMMON_RULES = [Rule("fits_makes", 1.5), Rule("fits_years", 1.5), Rule("pack_count", 1, tolerance=0.0)]
DEFAULT_WEIGHT = 1.0
DEFAULT_TOLERANCE = 0.1
TITLE_WEIGHT = 3.0
MISSING_PENALTY = 0.25  # share of a rule's weight lost when the found product doesn't state it
HARD_MISMATCH_CAP = 0.3
OTHER_CATEGORY_CAP = 0.2
# Not compared: identity fields, and brand (another brand with the same spec is the point).
SKIP = {"brand", "gtin", "part_number", "item_weight_lb"}

_STOP = {
    "the", "and", "for", "with", "w", "of", "a", "an", "in", "to", "by", "pack", "new", "-", "&", "x",
    "inch", "in.", "lbs", "lb", "free", "shipping", "sale", "item", "includes", "kit",
}


def tokens(title: str, drop: set[str] | None = None) -> set[str]:
    text = title.lower()
    text = re.sub(r"\bw/\s*", "with ", text)
    text = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)                              # 12,000 -> 12000
    text = re.sub(r"\b(\d{1,3})k\b", lambda m: str(int(m.group(1)) * 1000), text)  # 12k -> 12000
    words = re.findall(r"[a-z0-9]+(?:[./-][a-z0-9]+)*", text)
    drop = drop or set()
    return {w for w in words if w not in _STOP and w not in drop and len(w) > 1}


def title_similarity(a: str, b: str, brands: set[str] | None = None) -> float:
    ta, tb = tokens(a, brands), tokens(b, brands)
    if not ta or not tb:
        return 0.0
    # Containment of the reference's words matters more than extra words in the result.
    overlap = len(ta & tb)
    return 0.6 * overlap / len(ta) + 0.4 * overlap / len(ta | tb)


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def compare_values(rule: Rule, a: Any, b: Any) -> float:
    if rule.feature == "fits_years" and isinstance(a, list) and isinstance(b, list):
        return 1.0 if max(a[0], b[0]) <= min(a[1], b[1]) else 0.0
    if isinstance(a, bool) or isinstance(b, bool):
        return 1.0 if a == b else 0.0
    if isinstance(a, list) or isinstance(b, list):
        sa = {str(v) for v in _norm(a if isinstance(a, list) else [a])}
        sb = {str(v) for v in _norm(b if isinstance(b, list) else [b])}
        return len(sa & sb) / max(len(sa), len(sb)) if sa and sb else 0.0
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        tol = DEFAULT_TOLERANCE if rule.tolerance is None else rule.tolerance
        if a == b:
            return 1.0
        rel = abs(a - b) / max(abs(a), abs(b))
        if rel <= tol:
            return 1.0
        return max(0.0, 1.0 - rel / 0.5) * 0.6
    return 1.0 if _norm(a) == _norm(b) else 0.0


def rules_for(category: str, ref_attrs: dict[str, Any]) -> list[Rule]:
    rules = {r.feature: r for r in RULES.get(category, []) + COMMON_RULES}
    for key in ref_attrs:
        if key not in rules and key not in SKIP:
            rules[key] = Rule(key, DEFAULT_WEIGHT)
    return list(rules.values())


def same_product(ref: dict[str, Any], cand: dict[str, Any], title_sim: float, ref_brand: str | None, cand_title: str) -> bool:
    for key in ("gtin", "part_number"):
        va, vb = ref.get(key), cand.get(key)
        if va and vb and str(va).lower().lstrip("0") == str(vb).lower().lstrip("0"):
            return True
    part = ref.get("part_number")
    if part and len(str(part)) >= 4 and re.search(rf"\b{re.escape(str(part))}\b", cand_title, re.I):
        return True
    brand_ok = bool(ref_brand) and ref_brand.lower() in cand_title.lower()
    return brand_ok and title_sim >= 0.85


def score(
    ref_category: str,
    ref_attrs: dict[str, Any],
    ref_title: str,
    cand_category: str,
    cand_attrs: dict[str, Any],
    cand_title: str,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Return {'score', 'comparisons', 'hard_mismatch', 'category_mismatch', 'title_similarity'}."""
    earned = possible = 0.0
    comparisons: list[dict[str, Any]] = []
    hard_mismatch = False

    for rule in rules_for(ref_category, ref_attrs):
        va, vb = ref_attrs.get(rule.feature), cand_attrs.get(rule.feature)
        if va is None:
            continue
        if vb is None:
            possible += rule.weight * MISSING_PENALTY
            continue
        s = compare_values(rule, va, vb)
        earned += s * rule.weight
        possible += rule.weight
        comparisons.append({
            "feature": rule.feature,
            "label": label(rule.feature),
            "reference": display_value(rule.feature, va),
            "candidate": display_value(rule.feature, vb),
            "match": "yes" if s >= 0.99 else "partial" if s >= 0.5 else "no",
        })
        if rule.hard and s < 0.99:
            hard_mismatch = True

    title_sim = title_similarity(ref_title, cand_title, brands)
    earned += title_sim * TITLE_WEIGHT
    possible += TITLE_WEIGHT

    total = earned / possible if possible else 0.0
    category_mismatch = ref_category != "other" and cand_category not in ("other", ref_category)
    if hard_mismatch:
        total = min(total, HARD_MISMATCH_CAP)
    if category_mismatch:
        total = min(total, OTHER_CATEGORY_CAP)
    return {
        "score": round(total, 3),
        "comparisons": comparisons,
        "hard_mismatch": hard_mismatch,
        "category_mismatch": category_mismatch,
        "title_similarity": round(title_sim, 3),
    }
