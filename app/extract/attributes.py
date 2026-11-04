"""Generic attribute extraction for any product.

Reads measurements with units out of titles, descriptions and spec tables and
normalizes them (12K -> 12000 lb, 2-5/16" -> 2.3125 in, 3 ton -> 6000 lb,
50 mm -> 1.97 in), labels each value from the words around it (a weight next
to "tongue" is a tongue weight, an inch value next to "ball" is a ball size),
and picks up common yes/no features such as sway control or "no shank".

Category-specific extractors in automotive.py run first; anything they
don't cover is filled in from here, so unknown product types still get useful,
comparable attributes.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

from .automotive import extract_features as automotive_features

# ------------------------------------------------------------------ helpers

_DENOMS = {2, 4, 8, 16, 32, 64}
_INCH = r"(?:\"|”|″|''|\s?-?\s?in\.?(?![a-z])|\s?-?\s?inch(?:es)?\b)"

_LENGTH_RE = re.compile(
    r"(?<![\d/.])(?:"
    r"(?P<whole>\d{1,3})(?:\s*-\s*|\s+)(?P<num>\d{1,2})\s*/\s*(?P<den>\d{1,2})"
    r"|(?P<fnum>\d{1,2})\s*/\s*(?P<fden>\d{1,2})"
    r"|(?P<dec>\d{1,4}(?:\.\d+)?)"
    r")(?P<unit>" + _INCH + r"|\s?mm\b|\s?cm\b)?",
    re.I,
)
_WEIGHT_RE = re.compile(
    r"(?<![\d.])(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<k>k)?\s*-?\s*"
    r"(?P<unit>lbs?\.?(?![a-z])|pounds?\b|#(?!\d)|tons?\b|kg\b)?",
    re.I,
)
_TORQUE_RE = re.compile(r"(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:ft\.?\s*-?\s*lbs?\.?|foot[- ]pounds?|lb[.-]?\s*ft\.?|n[·.]?m\b)", re.I)
_DIMS_RE = re.compile(
    r"(?P<a>\d+(?:\.\d+)?)\s*(?:\"|inch(?:es)?|in\.?)?\s*[x×]\s*(?P<b>\d+(?:\.\d+)?)\s*(?:\"|inch(?:es)?|in\.?)?"
    r"(?:\s*[x×]\s*(?P<c>\d+(?:\.\d+)?))?\s*(?P<unit>\"|in(?:ch(?:es)?)?\b|cm\b|mm\b)?",
    re.I,
)
_CLASS_RE = re.compile(r"\bclass\s*(?P<c>V|IV|III|II|I|[1-5])\b", re.I)
_SIMPLE_UNITS: list[tuple[str, re.Pattern, float]] = [
    ("voltage_v", re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*-?\s*(?:v|volts?)\b", re.I), 1),
    ("capacity_ah", re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*-?\s*(?:ah|amp[- ]?hours?)\b", re.I), 1),
    ("current_a", re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*-?\s*(?:a|amps?)\b(?![- ]?h)", re.I), 1),
    ("power_w", re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*-?\s*(?:w|watts?)\b", re.I), 1),
    ("pressure_psi", re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*-?\s*psi\b", re.I), 1),
    ("brightness_lm", re.compile(r"(?<![\d.])(\d[\d,]*)\s*-?\s*(?:lm|lumens?)\b", re.I), 1),
    ("length_ft", re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*-?\s*(?:ft\.?|feet|foot)\b(?!\s*-?\s*lb)", re.I), 1),
]
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}

_TOW_CONTEXT = re.compile(r"hitch|tow|trailer|capacity|\blbs?\b|jack|winch|lift|hoist|ramp|rack|carrier|rated|rating|gtw|load", re.I)

# Words near a number that tell us what the number measures.
_WEIGHT_LABELS = [
    ("tongue_weight_lb", re.compile(r"tongue|\btw\b|spring bars?", re.I)),
    ("item_weight_lb", re.compile(r"item weight|product weight|shipping weight|unit weight|net weight|^weight\b|weighs", re.I)),
    ("weight_rating_lb", re.compile(r"gtw|gross|trailer weight|tow(?:ing)?|capacity|rating|rated|max(?:imum)?|load|hitch|\bwd\b|weight dist", re.I)),
]
_LENGTH_LABELS = [
    ("ball_diameter_in", re.compile(r"\bball\b", re.I)),
    ("receiver_size_in", re.compile(r"receiver|shank|hitch opening|tube", re.I)),
    ("drop_in", re.compile(r"\bdrop\b|\brise\b", re.I)),
    ("length_in", re.compile(r"\blength\b|\blong\b", re.I)),
    ("width_in", re.compile(r"\bwidth\b|\bwide\b", re.I)),
    ("height_in", re.compile(r"\bheight\b|\btall\b|\bhigh\b", re.I)),
    ("diameter_in", re.compile(r"diameter|\bdia\b", re.I)),
    ("thickness_in", re.compile(r"thick", re.I)),
]

# Yes/no and categorical features worth comparing across many product types.
_FLAGS: list[tuple[str, Any, re.Pattern]] = [
    ("sway_control", True, re.compile(r"sway control|anti[- ]?sway|sway bar|w/\s*sway|with sway", re.I)),
    ("shank_included", False, re.compile(r"no shank|without shank|shank (?:not|sold separately)|less shank|shank not incl", re.I)),
    ("shank_included", True, re.compile(r"(?:with|includes?|incl\.?)\s+(?:\d[\d\-/\" ]*\s*)?shank", re.I)),
    ("ball_included", False, re.compile(r"no ball|without ball|ball (?:not|sold separately)|less ball", re.I)),
    ("bar_type", "round bar", re.compile(r"round[- ]bar", re.I)),
    ("bar_type", "trunnion", re.compile(r"trunnion", re.I)),
    ("bar_type", "square bar", re.compile(r"square[- ]bar", re.I)),
    ("adjustable", True, re.compile(r"\badjustable\b", re.I)),
    ("waterproof", True, re.compile(r"waterproof|ip6[5-8]", re.I)),
    ("wireless", True, re.compile(r"\bwireless\b|bluetooth", re.I)),
    ("cordless", True, re.compile(r"\bcordless\b", re.I)),
    ("material", "stainless steel", re.compile(r"stainless", re.I)),
    ("material", "aluminum", re.compile(r"alumin(?:um|ium)", re.I)),
    ("material", "carbon fiber", re.compile(r"carbon fib", re.I)),
    ("material", "steel", re.compile(r"\bsteel\b", re.I)),
]


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _context(text: str, start: int, end: int, before: int = 32, after: int = 22) -> tuple[str, str]:
    """Words around a number, cut at the neighbouring number or comma so labels don't leak."""
    pre = re.split(r"[,;()\d~]", text[max(0, start - before):start])[-1]
    post = re.split(r"[,;()\d~]", text[end:end + after])[0]
    return pre, post


def _label(labels, before: str, after: str) -> str | None:
    # Words immediately after the number win ("2-5/16 ball"), then words before ("ball size: 2").
    for key, pattern in labels:
        if pattern.search(after):
            return key
    for key, pattern in labels:
        if pattern.search(before):
            return key
    return None


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = "~"
    return "".join(chars)


def fix_slug_fractions(text: str) -> str:
    """URL slugs drop the slash: '2-516-ball' really means 2-5/16 ball."""
    def repl(m: re.Match) -> str:
        digits = m.group("frac")
        for split in range(1, len(digits)):
            num, den = int(digits[:split]), int(digits[split:])
            if den in _DENOMS and 0 < num < den:
                return f"{m.group('whole')}-{num}/{den}{m.group('tail')}"
        return m.group(0)

    return re.sub(r"\b(?P<whole>\d)[- ](?P<frac>\d{2,4})(?P<tail>\s*(?:in\b|inch|\"|ball|shank|receiver))", repl, text, flags=re.I)


def format_inches(value: float) -> str:
    whole = int(value)
    frac = Fraction(value - whole).limit_denominator(64)
    if frac == 0 or abs(float(frac) - (value - whole)) > 0.002:
        return f'{value:g}"'
    if frac == 1:
        return f'{whole + 1}"'
    return f'{whole}-{frac.numerator}/{frac.denominator}"' if whole else f'{frac.numerator}/{frac.denominator}"'


# ------------------------------------------------------------------ measurements


def measurements(text: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    text = fix_slug_fractions(text.replace("\u00a0", " "))
    # "8K - 12K" or "5,000-10,000 lbs": keep the upper bound, which is the rating.
    text = re.sub(
        r"(?<![\d/])\d[\d,]*(?:\.\d+)?\s*k?\s*(?:-|–|to)\s*(?=\d[\d,]*(?:\.\d+)?\s*(?:k\b|lbs?\b|pounds?\b))",
        "",
        text,
        flags=re.I,
    )
    used: list[tuple[int, int]] = []

    def put(key: str, value: Any) -> None:
        attrs.setdefault(key, value)

    # Torque first so "ft-lb" isn't read as a weight.
    for m in _TORQUE_RE.finditer(text):
        val = _num(m.group("num"))
        if m.group(0).lower().replace("·", ".").rstrip(".").endswith(("n.m", "nm")):
            val = round(val * 0.737562, 1)
        put("torque_ftlb", val)
        used.append(m.span())

    for m in _DIMS_RE.finditer(text):
        values = [float(v) for v in (m.group("a"), m.group("b"), m.group("c")) if v]
        unit = (m.group("unit") or "").lower()
        if not unit and not m.group("c"):
            continue  # "2 x 4" alone is too ambiguous
        factor = 1 / 25.4 if unit == "mm" else 1 / 2.54 if unit == "cm" else 1
        put("dimensions_in", sorted((round(v * factor, 2) for v in values), reverse=True))
        used.append(m.span())

    masked = _mask(text, used)
    tow_context = bool(_TOW_CONTEXT.search(text))

    for m in _WEIGHT_RE.finditer(masked):
        unit = (m.group("unit") or "").lower().rstrip(".")
        k = m.group("k")
        if not unit and not k:
            continue
        if k and not unit and not tow_context:
            continue  # "4K" on a dash cam is a resolution, not 4000 lb
        value = _num(m.group("num")) * (1000 if k else 1)
        if unit.startswith("ton"):
            value *= 2000
        elif unit == "kg":
            value = round(value * 2.20462)
        before, after = _context(masked, *m.span())
        key = _label(_WEIGHT_LABELS, before, after)
        if key is None:
            key = "weight_rating_lb" if (k or value >= 1000 or unit.startswith("ton")) else "item_weight_lb"
        if key == "weight_rating_lb" and value < 50:
            continue
        put(key, value)
        used.append(m.span())

    masked = _mask(text, used)
    for m in _LENGTH_RE.finditer(masked):
        unit = (m.group("unit") or "").strip().lower()
        if m.group("whole"):
            num, den = int(m.group("num")), int(m.group("den"))
            if den not in _DENOMS or not 0 < num < den:
                continue
            value = int(m.group("whole")) + num / den
        elif m.group("fnum"):
            num, den = int(m.group("fnum")), int(m.group("fden"))
            if den not in _DENOMS or not 0 < num < den:
                continue
            value = num / den
        else:
            value = float(m.group("dec"))
        before, after = _context(masked, *m.span())
        key = _label(_LENGTH_LABELS, before, after)
        if not unit:
            # A bare number only counts when a strong word sits right next to it ("2-5/16 ball").
            if key is None or not re.match(r"\s*-?\s*(ball|receiver|shank|drop|rise)\b", after, re.I):
                continue
        if unit == "mm":
            value /= 25.4
        elif unit == "cm":
            value /= 2.54
        if value <= 0 or value > 600:
            continue
        put(key or "size_in", round(value, 4))

    for m in _CLASS_RE.finditer(text):
        c = m.group("c").upper()
        put("class", _ROMAN.get(c, int(c) if c.isdigit() else c))
        break

    for key, pattern, factor in _SIMPLE_UNITS:
        m = pattern.search(masked)
        if m:
            put(key, _num(m.group(1)) * factor)

    for key, value, pattern in _FLAGS:
        if key not in attrs and pattern.search(text):
            attrs[key] = value
    return attrs


# ------------------------------------------------------------------ entry point


def analyze(
    title: str,
    description: str | None = None,
    specs: dict[str, str] | None = None,
    brand: str | None = None,
    category_hint: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (category, attributes) for any product."""
    title = fix_slug_fractions(title or "")
    specs = specs or {}
    category, attrs = automotive_features(title, description, specs, brand=brand, category_hint=category_hint)

    # Title is the most trustworthy; spec rows next (key gives context); description last.
    for key, value in measurements(title).items():
        attrs.setdefault(key, value)
    for spec_key, spec_value in specs.items():
        for key, value in measurements(f"{spec_key}: {spec_value}").items():
            attrs.setdefault(key, value)
    if description:
        for key, value in measurements(description[:4000]).items():
            attrs.setdefault(key, value)
    return category, attrs


def display_value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        if key == "fits_years" and len(value) == 2:
            return f"{value[0]}–{value[1]}"
        if key == "dimensions_in":
            return " x ".join(f"{v:g}" for v in value) + " in"
        return ", ".join(str(v) for v in value)
    if isinstance(value, (int, float)):
        if key.endswith("_in"):
            return format_inches(float(value))
        if key.endswith("_lb"):
            return f"{value:,.0f} lb"
        suffix = {"_ftlb": " ft-lb", "_v": " V", "_a": " A", "_ah": " Ah", "_w": " W", "_psi": " psi",
                  "_lm": " lm", "_ft": " ft", "_quarts": " qt", "_mm": " mm", "_k": " K", "_miles": " mi"}
        for end, unit in suffix.items():
            if key.endswith(end):
                return f"{value:g}{unit}"
        return f"{value:g}"
    return str(value)


def label(key: str) -> str:
    key = re.sub(r"_(in|lb|ftlb|v|a|ah|w|psi|lm|ft|quarts|mm|k|miles)$", "", key)
    return key.replace("_", " ").capitalize()
