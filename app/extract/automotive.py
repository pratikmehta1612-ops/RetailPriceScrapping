"""Turn product titles, descriptions and spec tables into normalized automotive features.

Each product gets a `category` and a flat dict of features whose keys are
shared across retailers, so a Walmart tire and an Amazon tire can be compared
field by field (size, load index, speed rating, season...).
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------- categories

# Ordered: the first category whose keywords match wins.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    # Towing first: their titles often mention balls, brakes and lights too.
    ("weight_distribution_hitch", (r"weight[- ]distribut", r"\bwd hitch", r"\bwdh\b",
                                   r"round[- ]bar hitch", r"trunnion[- ](?:bar )?hitch",
                                   r"sway control hitch", r"\b[24][- ]point\b.*\bhitch")),
    ("sway_control_kit", (r"sway control (?:kit|unit|bar)\b", r"friction sway")),
    ("brake_controller", (r"brake controller",)),
    ("trailer_wiring", (r"wiring harness|trailer wiring|[47][- ]way (?:plug|connector|adapter)|[47][- ]pin",)),
    ("tongue_jack", (r"tongue jack|trailer jack|a-frame jack",)),
    ("trailer_coupler", (r"\bcoupler\b",)),
    ("ball_mount", (r"ball mount|draw ?bar\b|\bshank\b.*\bdrop\b",)),
    ("hitch_ball", (r"hitch ball|trailer ball|tow ball",)),
    ("receiver_hitch", (r"receiver hitch|trailer hitch|tow hitch|class (?:i{1,3}|iv|v|[1-5]) hitch",)),
    ("tire", (r"\btires?\b", r"\btyres?\b", r"(?<!\d)\d{3}/\d{2}\s?Z?R\s?\d{2}\b")),
    ("wiper_blade", (r"wiper", r"windshield blade")),
    ("battery", (r"\bbattery\b", r"\bbatteries\b", r"\bcca\b", r"cold cranking")),
    ("motor_oil", (r"motor oil", r"engine oil", r"\b\d{1,2}w-?\d{2}\b")),
    ("brake_pads", (r"brake pads?", r"\bbrake\b.*\bpads?\b", r"disc brake pad")),
    ("brake_rotor", (r"\brotors?\b",)),
    ("oil_filter", (r"oil filter",)),
    ("cabin_air_filter", (r"cabin (air )?filter",)),
    ("engine_air_filter", (r"(engine )?air filter",)),
    ("spark_plug", (r"spark plugs?",)),
    ("headlight_bulb", (r"headlight|fog light|bulb|\bled\b.*\b(h\d{1,2}|9005|9006)\b",)),
    ("coolant", (r"coolant|antifreeze",)),
    ("transmission_fluid", (r"transmission fluid|\batf\b|\bcvt fluid",)),
    ("brake_fluid", (r"brake fluid|\bdot ?[345]\b",)),
    ("floor_mats", (r"floor (mats?|liners?)",)),
    ("dash_cam", (r"dash ?cam",)),
    ("jump_starter", (r"jump starter|jump box",)),
    ("car_charger", (r"car charger|usb.?c car",)),
]

CAR_MAKES = (
    "Acura Audi BMW Buick Cadillac Chevrolet Chevy Chrysler Dodge Fiat Ford GMC Genesis Honda "
    "Hyundai Infiniti Jaguar Jeep Kia Lexus Lincoln Mazda Mercedes-Benz Mercedes Mini Mitsubishi "
    "Nissan Porsche Ram Subaru Tesla Toyota Volkswagen VW Volvo Rivian Lucid Polestar"
).split()

BULB_CODES = (
    "H1 H3 H4 H7 H8 H9 H10 H11 H13 H16 9003 9004 9005 9006 9007 9008 9011 9012 "
    "HB2 HB3 HB4 HB5 D1S D2S D3S D4S D2R 880 881 194 168 1156 1157 3156 3157 7440 7443 921 912"
).split()

# ---------------------------------------------------------------- regexes

TIRE_SIZE = re.compile(
    r"\b(?P<prefix>P|LT|ST)?\s?(?P<width>\d{3})\s?/\s?(?P<aspect>\d{2})\s?(?P<construction>Z?R|-|D|B)\s?"
    r"(?P<rim>\d{2}(?:\.5)?)\b(?:\s*(?P<load>\d{2,3}(?:/\d{2,3})?)\s?(?P<speed>[A-HJ-NP-Z]|[VWY]R?|ZR)\b)?",
    re.I,
)
FLOTATION_TIRE = re.compile(r"\b(?P<dia>\d{2})\s?x\s?(?P<width>\d{1,2}\.\d{2})\s?R\s?(?P<rim>\d{2})\b", re.I)
VISCOSITY = re.compile(r"\b(?P<cold>0|5|10|15|20|25)\s?W\s?-?\s?(?P<hot>\d{2})\b", re.I)
VOLUME = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*-?\s*(?P<unit>quarts?|qts?\.?|gallons?|gal\.?|liters?|litres?|l\b|"
    r"fl\.?\s?oz|fluid ounces?|ounces?|oz\b)",
    re.I,
)
PACK = re.compile(r"(?:pack of|set of|case of)\s*(?P<n>\d+)|(?P<m>\d+)\s*-?\s*(?:pack|pk|count|ct|pcs|pieces)\b", re.I)
GROUP_SIZE = re.compile(r"\b(?:bci\s*)?group\s*(?:size\s*)?:?\s*(?P<g>H\d|\d{2,3}[A-Z]{0,2}(?:/\d{2,3}[A-Z]?)?)\b", re.I)
CCA = re.compile(r"(?P<n>\d{3,4})\s*(?:cca|cold cranking amps?)\b|(?:cca|cold cranking amps?)\s*:?\s*(?P<m>\d{3,4})", re.I)
RESERVE = re.compile(r"(?P<n>\d{2,3})\s*(?:min(?:utes)?\.?)?\s*reserve|reserve capacity\s*:?\s*(?P<m>\d{2,3})", re.I)
VOLTAGE = re.compile(r"\b(?P<v>6|12|24)\s?-?\s?v(?:olts?)?\b", re.I)
WIPER_LEN = re.compile(r"\b(?P<len>1[0-9]|2[0-9]|3[0-2])\s?(?:-|\s)?(?:\"|”|''|in\b|inch(?:es)?\b)", re.I)
FITMENT_YEARS = re.compile(r"\b(?P<start>(?:19[89]|20[0-3])\d)\s?(?:-|–|to|thru)\s?(?P<end>(?:19[89]|20[0-3])\d|\d{2})\b")
SINGLE_YEAR = re.compile(r"\b(?P<y>(?:19[89]|20[0-3])\d)\b")
PART_NUMBER = re.compile(r"\b(?:part|model|mfr|item)\s*(?:number|no\.?|#)\s*:?\s*(?P<pn>[A-Z0-9][A-Z0-9\-]{3,19})\b", re.I)
WARRANTY = re.compile(r"(?P<n>\d{1,3}(?:,\d{3})?)\s*-?\s*(?P<unit>mile|month|year)s?\b.{0,20}warranty", re.I)
DOT = re.compile(r"\bDOT\s?(?P<n>[345](?:\.1)?)\b", re.I)


def _first(pattern: re.Pattern, text: str) -> re.Match | None:
    return pattern.search(text)


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _spec(specs: dict[str, str], *keys: str) -> str | None:
    """Case-insensitive, substring lookup in a spec table."""
    lowered = {k.lower(): v for k, v in specs.items()}
    for key in keys:
        key = key.lower()
        if key in lowered:
            return lowered[key]
    for key in keys:
        for k, v in lowered.items():
            if key in k:
                return v
    return None


def detect_category(text: str, hint: str | None = None) -> str:
    haystack = f"{hint or ''} {text}".lower()
    for category, patterns in CATEGORY_KEYWORDS:
        if any(re.search(p, haystack, re.I) for p in patterns):
            return category
    return "other"


def volume_in_quarts(text: str) -> float | None:
    """Total liquid volume in US quarts (handles '6-pack of 1 quart', '5 qt jug')."""
    match = _first(VOLUME, text)
    if not match:
        return None
    num = float(match.group("num"))
    unit = match.group("unit").lower().replace(".", "").replace(" ", "")
    if unit.startswith(("quart", "qt")):
        quarts = num
    elif unit.startswith(("gallon", "gal")):
        quarts = num * 4
    elif unit.startswith(("liter", "litre")) or unit == "l":
        quarts = num * 1.05669
    else:  # ounces
        quarts = num / 32
    return round(quarts, 2)


def pack_count(text: str) -> int | None:
    match = _first(PACK, text)
    if not match:
        return None
    n = int(match.group("n") or match.group("m"))
    return n if 1 < n <= 500 else None


def fitment(text: str) -> dict[str, Any]:
    makes = sorted(
        {("Chevrolet" if m.lower() == "chevy" else "Volkswagen" if m.lower() == "vw" else m)
         for m in CAR_MAKES if re.search(rf"\b{re.escape(m)}\b", text, re.I)}
    )
    result: dict[str, Any] = {}
    if makes:
        result["fits_makes"] = makes
    years = _first(FITMENT_YEARS, text)
    if years:
        start = int(years.group("start"))
        end_raw = years.group("end")
        end = int(end_raw) if len(end_raw) == 4 else int(str(start)[:2] + end_raw)
        if start <= end:
            result["fits_years"] = [start, end]
    elif makes:
        single = _first(SINGLE_YEAR, text)
        if single:
            year = int(single.group("y"))
            result["fits_years"] = [year, year]
    return result


# ---------------------------------------------------------------- per category

def _tire(text: str, specs: dict[str, str]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    size_text = _spec(specs, "tire size", "size") or ""
    match = _first(TIRE_SIZE, size_text) or _first(TIRE_SIZE, text)
    if match:
        f["tire_width_mm"] = int(match.group("width"))
        f["aspect_ratio"] = int(match.group("aspect"))
        f["rim_diameter_in"] = float(match.group("rim"))
        f["tire_size"] = f"{match.group('width')}/{match.group('aspect')}R{match.group('rim')}"
        if match.group("prefix"):
            f["tire_type"] = match.group("prefix").upper()
        if match.group("load"):
            f["load_index"] = match.group("load")
        if match.group("speed"):
            speed_code = match.group("speed").upper()
            f["speed_rating"] = speed_code[0] if len(speed_code) == 2 else speed_code
    else:
        flot = _first(FLOTATION_TIRE, text)
        if flot:
            f["tire_size"] = f"{flot.group('dia')}x{flot.group('width')}R{flot.group('rim')}"
            f["rim_diameter_in"] = float(flot.group("rim"))
    load = _spec(specs, "load index")
    if load and "load_index" not in f:
        m = re.search(r"\d{2,3}", load)
        if m:
            f["load_index"] = m.group(0)
    speed = _spec(specs, "speed rating")
    if speed and "speed_rating" not in f:
        m = re.search(r"\b([A-HJ-NP-Z])\b", speed.upper())
        if m:
            f["speed_rating"] = m.group(1)
    lowered = text.lower()
    for season, keys in (
        ("all-terrain", ("all-terrain", "all terrain", " a/t", "at tire")),
        ("mud-terrain", ("mud-terrain", "mud terrain", " m/t")),
        ("winter", ("winter", "snow", "studless")),
        ("all-weather", ("all-weather", "all weather")),
        ("summer", ("summer", "max performance", "ultra high performance")),
        ("all-season", ("all-season", "all season")),
    ):
        if any(k in lowered for k in keys):
            f["season"] = season
            break
    if "run flat" in lowered or "run-flat" in lowered or "runflat" in lowered:
        f["run_flat"] = True
    tread = re.search(r"(\d{2,3}(?:,\d{3})?)\s*-?\s*mile", lowered)
    if tread:
        f["treadwear_warranty_miles"] = int(tread.group(1).replace(",", ""))
    return f


def _motor_oil(text: str, specs: dict[str, str]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    visc = _first(VISCOSITY, _spec(specs, "viscosity", "sae") or "") or _first(VISCOSITY, text)
    if visc:
        f["viscosity"] = f"{visc.group('cold')}W-{visc.group('hot')}"
    lowered = text.lower()
    if "high mileage" in lowered:
        f["oil_type"] = "high mileage"
    elif "full synthetic" in lowered or "fully synthetic" in lowered or "100% synthetic" in lowered:
        f["oil_type"] = "full synthetic"
    elif "synthetic blend" in lowered or "semi-synthetic" in lowered or "semi synthetic" in lowered:
        f["oil_type"] = "synthetic blend"
    elif "synthetic" in lowered:
        f["oil_type"] = "full synthetic"
    elif "conventional" in lowered:
        f["oil_type"] = "conventional"
    if "diesel" in lowered:
        f["engine"] = "diesel"
    for standard in ("dexos1", "dexos 1", "api sp", "api sn", "ilsac gf-6", "acea c3", "vw 504", "mb 229"):
        if standard in lowered:
            f.setdefault("approvals", []).append(standard.upper().replace("DEXOS 1", "DEXOS1"))
    return f


def _battery(text: str, specs: dict[str, str]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    group = _first(GROUP_SIZE, (_spec(specs, "group size", "bci") or "") + " " + text)
    if group:
        f["group_size"] = group.group("g").upper()
    cca_text = (_spec(specs, "cold cranking", "cca") or "") + " " + text
    cca = _first(CCA, cca_text)
    if cca:
        f["cca"] = int(cca.group("n") or cca.group("m"))
    else:
        spec_cca = _spec(specs, "cold cranking", "cca")
        if spec_cca and re.search(r"\d{3,4}", spec_cca):
            f["cca"] = int(re.search(r"\d{3,4}", spec_cca).group(0))
    reserve = _first(RESERVE, text)
    if reserve:
        f["reserve_capacity_min"] = int(reserve.group("n") or reserve.group("m"))
    volt = _first(VOLTAGE, text)
    f["voltage"] = int(volt.group("v")) if volt else 12
    lowered = text.lower()
    if "agm" in lowered or "absorbed glass" in lowered:
        f["chemistry"] = "AGM"
    elif "efb" in lowered or "enhanced flooded" in lowered:
        f["chemistry"] = "EFB"
    elif "lithium" in lowered or "lifepo4" in lowered:
        f["chemistry"] = "lithium"
    elif "flooded" in lowered or "lead acid" in lowered or "lead-acid" in lowered:
        f["chemistry"] = "flooded"
    warranty = re.search(r"(\d)\s*-?\s*year", lowered)
    if warranty:
        f["warranty_years"] = int(warranty.group(1))
    return f


def _wiper(text: str, specs: dict[str, str]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    lengths = [int(m.group("len")) for m in WIPER_LEN.finditer((_spec(specs, "length", "size") or "") + " " + text)]
    if lengths:
        f["blade_length_in"] = lengths[0]
        if len(set(lengths)) > 1:
            f["blade_lengths_in"] = sorted(set(lengths))
    lowered = text.lower()
    for style in ("hybrid", "beam", "conventional", "winter", "rear"):
        if style in lowered:
            f["blade_style"] = style
            break
    return f


def _brake(text: str, specs: dict[str, str]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    lowered = text.lower()
    for material in ("ceramic", "semi-metallic", "semi metallic", "organic", "metallic"):
        if material in lowered:
            f["pad_material"] = material.replace(" ", "-")
            break
    if "front and rear" in lowered or "front & rear" in lowered:
        f["position"] = "front+rear"
    elif "front" in lowered:
        f["position"] = "front"
    elif "rear" in lowered:
        f["position"] = "rear"
    return f


def _bulb(text: str, specs: dict[str, str]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    codes = [c for c in BULB_CODES if re.search(rf"(?<![\w.]){re.escape(c)}(?![\w.])", text, re.I)]
    if codes:
        f["bulb_code"] = codes[0].upper()
        if len(codes) > 1:
            f["bulb_codes"] = [c.upper() for c in codes]
    lowered = text.lower()
    for tech in ("led", "hid", "xenon", "halogen"):
        if re.search(rf"\b{tech}\b", lowered):
            f["bulb_tech"] = "HID" if tech in ("hid", "xenon") else tech.upper() if tech == "led" else tech
            break
    lumens = re.search(r"(\d{1,3}(?:,\d{3})*)\s*(?:lm|lumens?)\b", lowered)
    if lumens:
        f["lumens"] = int(lumens.group(1).replace(",", ""))
    kelvin = re.search(r"(\d{4})\s?k\b", lowered)
    if kelvin:
        f["color_temp_k"] = int(kelvin.group(1))
    return f


def _plug(text: str, specs: dict[str, str]) -> dict[str, Any]:
    lowered = text.lower()
    for material in ("iridium", "platinum", "copper"):
        if material in lowered:
            return {"electrode": material}
    return {}


def _fluid(text: str, specs: dict[str, str]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    lowered = text.lower()
    if "50/50" in lowered or "prediluted" in lowered or "pre-diluted" in lowered or "ready to use" in lowered:
        f["mix"] = "50/50"
    elif "concentrate" in lowered:
        f["mix"] = "concentrate"
    dot = _first(DOT, text)
    if dot:
        f["dot_rating"] = f"DOT {dot.group('n')}"
    for kind in ("dexron vi", "mercon v", "mercon lv", "cvt", "multi-vehicle", "universal"):
        if kind in lowered:
            f["spec"] = kind
            break
    return f


CATEGORY_EXTRACTORS = {
    "tire": _tire,
    "motor_oil": _motor_oil,
    "battery": _battery,
    "wiper_blade": _wiper,
    "brake_pads": _brake,
    "headlight_bulb": _bulb,
    "spark_plug": _plug,
    "coolant": _fluid,
    "transmission_fluid": _fluid,
    "brake_fluid": _fluid,
}

# Units for per-unit price comparison.
UNIT_FOR_CATEGORY = {
    "motor_oil": "quart",
    "coolant": "quart",
    "transmission_fluid": "quart",
    "brake_fluid": "quart",
}


def extract_features(
    title: str,
    description: str | None = None,
    specs: dict[str, str] | None = None,
    brand: str | None = None,
    category_hint: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (category, features) for a product."""
    specs = specs or {}
    spec_text = " ".join(f"{k}: {v}" for k, v in specs.items())
    # Title is the most reliable signal; description and specs fill gaps.
    primary = title or ""
    full = " ".join(filter(None, [title, description or "", spec_text]))

    category = detect_category(primary, category_hint)
    if category == "other":
        category = detect_category(full, category_hint)

    features: dict[str, Any] = {}
    extractor = CATEGORY_EXTRACTORS.get(category)
    if extractor:
        # Run on title first, then fill missing values from the longer text.
        features.update(extractor(primary, specs))
        for key, value in extractor(full, specs).items():
            features.setdefault(key, value)

    if brand:
        features["brand"] = brand.strip()
    quarts = volume_in_quarts(primary) or volume_in_quarts(_spec(specs, "volume", "capacity", "size") or "")
    packs = pack_count(primary)
    if category in UNIT_FOR_CATEGORY and quarts:
        features["volume_quarts"] = round(quarts * (packs or 1), 2)
    if packs:
        features["pack_count"] = packs
    part = _first(PART_NUMBER, spec_text) or _first(PART_NUMBER, full)
    part_spec = _spec(specs, "part number", "manufacturer part", "model number", "mpn")
    if part_spec:
        features["part_number"] = part_spec.split()[0].upper()
    elif part:
        features["part_number"] = part.group("pn").upper()
    features.update({k: v for k, v in fitment(full).items() if k not in features})
    return category, features


def unit_price(category: str, features: dict[str, Any], price: float | None) -> tuple[float | None, str | None]:
    """Price per quart for fluids, per item for multi-packs, else None."""
    if price is None:
        return None, None
    unit = UNIT_FOR_CATEGORY.get(category)
    if unit == "quart" and features.get("volume_quarts"):
        return round(price / features["volume_quarts"], 2), "quart"
    if features.get("pack_count"):
        return round(price / features["pack_count"], 2), "item"
    return None, None
