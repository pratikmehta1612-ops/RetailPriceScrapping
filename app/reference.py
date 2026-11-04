"""Read the reference product: from its page, from a typed description, or both."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .extract.attributes import analyze, fix_slug_fractions
from .fetcher import FetchError, Fetcher
from .scrapers import scrape_html

CATEGORY_PHRASES = {
    "weight_distribution_hitch": "weight distribution hitch",
    "sway_control_kit": "sway control kit",
    "brake_controller": "trailer brake controller",
    "trailer_wiring": "trailer wiring harness",
    "tongue_jack": "trailer tongue jack",
    "trailer_coupler": "trailer coupler",
    "ball_mount": "hitch ball mount",
    "hitch_ball": "trailer hitch ball",
    "receiver_hitch": "trailer receiver hitch",
    "tire": "tire",
    "wiper_blade": "wiper blade",
    "battery": "car battery",
    "motor_oil": "motor oil",
    "brake_pads": "brake pads",
    "brake_rotor": "brake rotor",
    "oil_filter": "oil filter",
    "cabin_air_filter": "cabin air filter",
    "engine_air_filter": "engine air filter",
    "spark_plug": "spark plug",
    "headlight_bulb": "headlight bulb",
    "coolant": "coolant antifreeze",
    "transmission_fluid": "transmission fluid",
    "brake_fluid": "brake fluid",
    "floor_mats": "floor mats",
    "dash_cam": "dash cam",
    "jump_starter": "jump starter",
    "car_charger": "car charger",
}


class Reference(BaseModel):
    url: str | None = None
    title: str
    brand: str | None = None
    price: float | None = None
    currency: str = "USD"
    image: str | None = None
    store: str | None = None
    category: str = "other"
    attributes: dict[str, Any] = Field(default_factory=dict)
    specs: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    notes: list[str] = Field(default_factory=list)
    page_text: str | None = Field(default=None, exclude=True)  # sent to Claude, not to the browser


_SITE_SUFFIX = re.compile(r"\s*(?:[|–—]|\s-\s)\s*[^|–—]{2,40}$")


def clean_title(title: str) -> str:
    title = re.sub(r"^(?:Amazon\.com\s*:\s*|Buy\s+)", "", title.strip(), flags=re.I)
    # "Product name | Overton's" / "Product - Walmart.com"
    stripped = _SITE_SUFFIX.sub("", title)
    if len(stripped) >= 15:
        title = stripped
    return re.sub(r"\s+", " ", title).strip()


def slug_title(url: str) -> str | None:
    """Readable words from the URL path, e.g. .../husky-round-bar-...-no-shank-146894.html."""
    path = unquote(urlsplit(url).path)
    segments = [s for s in path.split("/") if s]
    best = max(segments, key=lambda s: s.count("-") + s.count("_"), default="")
    best = re.sub(r"\.(?:html?|aspx?|php)$", "", best, flags=re.I)
    best = re.sub(r"[-_](?:\d{5,}|[a-z]?\d{6,}[a-z]?)$", "", best, flags=re.I)  # trailing product id
    words = re.sub(r"[-_+]+", " ", best).strip()
    if words.count(" ") < 2:
        return None
    return fix_slug_fractions(words)


def guess_brand(title: str) -> str | None:
    first = re.match(r"([A-Z][\w'&.-]+(?:-[A-Z][\w']+)*)", title.strip())
    return first.group(1) if first else None


def visible_text(html: str, limit: int = 12000) -> str:
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript, svg, nav, header, footer, iframe"):
        node.decompose()
    body = tree.body or tree.root
    text = body.text(deep=True, separator="\n") if body else ""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if len(ln) > 2]
    return "\n".join(lines)[:limit]


async def read_reference(url: str | None, details: str | None, fetcher: Fetcher | None) -> Reference:
    url = (url or "").strip() or None
    details = (details or "").strip() or None
    if not url and not details:
        raise ValueError("Enter a product link, a product name, or both.")

    notes: list[str] = []
    data: dict[str, Any] = {}
    page_text = None
    slug = slug_title(url) if url else None

    if url and fetcher is not None:
        try:
            html = await fetcher.get_text(url)
            page_text = visible_text(html)
            try:
                scraped = scrape_html(url, html)
                data = scraped.model_dump()
            except ValueError:
                notes.append("The page didn't contain readable product data; used the link text instead.")
        except FetchError as exc:
            notes.append(f"Couldn't read the product page ({exc}). Used the words in the link instead.")

    title = clean_title(data.get("title") or "") or (details.splitlines()[0][:200] if details and not slug else None) or (slug or "")
    if not title:
        raise ValueError("Couldn't work out the product from that link. Type the product name in the details box.")
    if slug and title == slug:
        title = title.title()

    # Many stores list specs as plain "Label: value" lines in the page body.
    specs = dict(data.get("specs") or {})
    for line in (page_text or "").splitlines():
        m = re.match(r"^([A-Za-z][\w /&().'-]{1,40}?)\s*:\s*(.{1,80})$", line)
        if m and re.search(r"\d|yes|no|included", m.group(2), re.I):
            specs.setdefault(m.group(1).strip(), m.group(2).strip().rstrip("."))
    data["specs"] = specs

    description_parts = [data.get("description"), slug if slug and slug.lower() != title.lower() else None, details]
    description = "\n".join(p for p in description_parts if p) or None
    brand = data.get("brand") or guess_brand(title)
    category, attributes = analyze(title, description, data.get("specs"), brand=brand, category_hint=data.get("category_hint"))

    return Reference(
        url=url,
        title=title,
        brand=brand,
        price=data.get("price"),
        currency=data.get("currency") or "USD",
        image=data.get("image"),
        store=urlsplit(url).netloc.removeprefix("www.") if url else None,
        category=category,
        attributes=attributes,
        specs=data.get("specs") or {},
        description=description,
        notes=notes,
        page_text="\n".join(filter(None, [details, page_text])) or None,
    )


# ------------------------------------------------------------------ search queries

_MODEL_NO = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{4,}\b")


def _search_value(key: str, value: Any) -> str | None:
    if isinstance(value, bool):
        phrases = {"sway_control": "sway control", "adjustable": "adjustable", "waterproof": "waterproof",
                   "wireless": "wireless", "cordless": "cordless"}
        if not value:
            return None
        return phrases.get(key)
    if key.endswith("_lb") and isinstance(value, (int, float)):
        return f"{value:,.0f} lb".replace(",", "")
    if key == "ball_diameter_in":
        from .extract.attributes import format_inches
        return f"{format_inches(value).rstrip(chr(34))} ball"
    if key == "receiver_size_in":
        from .extract.attributes import format_inches
        return f"{format_inches(value).rstrip(chr(34))} inch receiver"
    if key in ("bar_type", "viscosity", "tire_size", "group_size", "bulb_code", "oil_type", "season"):
        return str(value)
    if key.endswith("_in") and isinstance(value, (int, float)):
        from .extract.attributes import format_inches
        return format_inches(value)
    return None


def build_queries(ref: Reference, max_queries: int = 3) -> list[str]:
    """Several angles: the exact product, the spec without the brand, and a broader spec search."""
    brand_words = {w.lower() for w in (ref.brand or "").split()}
    plain = re.sub(r"\bw/\s*", "with ", ref.title, flags=re.I)
    plain = re.sub(r"[,()|]+|(?<!\d)/|/(?!\d)", " ", plain)
    plain = " ".join(plain.split())
    exact = " ".join(plain.split()[:16])

    spec_bits = []
    priority = ["bar_type", "weight_rating_lb", "ball_diameter_in", "sway_control", "receiver_size_in",
                "tongue_weight_lb", "tire_size", "viscosity", "group_size", "bulb_code", "blade_length_in",
                "oil_type", "season"]
    keys = priority + [k for k in ref.attributes if k not in priority]
    for key in keys:
        if key in ref.attributes:
            bit = _search_value(key, ref.attributes[key])
            if bit and bit.lower() not in " ".join(spec_bits).lower():
                spec_bits.append(bit)

    phrase = CATEGORY_PHRASES.get(ref.category)
    if phrase is None:
        words = [w for w in plain.split() if w.lower() not in brand_words and not _MODEL_NO.match(w)]
        phrase = " ".join(words[:6])

    queries = [exact]
    if spec_bits:
        queries.append(" ".join([phrase] + spec_bits[:4]))
        queries.append(" ".join([phrase] + spec_bits[:2]))
    else:
        unbranded = " ".join(w for w in plain.split() if w.lower() not in brand_words)
        queries.append(" ".join(unbranded.split()[:10]))
        queries.append(phrase)

    seen, unique = set(), []
    for q in queries:
        key = q.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(q.strip())
    return unique[:max_queries]
