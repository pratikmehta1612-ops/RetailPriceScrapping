"""Find products similar to a reference product.

1. Read the reference (page, link words, typed details) and extract attributes.
2. Optionally let Claude list the key attributes and write search queries.
3. Search Google Shopping with a few queries; merge and de-duplicate.
4. Score each result against the reference (rules, plus Claude when enabled).
5. Keep the best matches, at least MIN_RESULTS of them.
6. Look up direct store links for the top results.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .ai import AIError, Claude
from .config import Settings
from .extract.attributes import analyze, display_value, label
from .matching import SKIP, rules_for, same_product, score as rule_score, title_similarity
from .reference import Reference, build_queries
from .search.serpapi import Candidate, Offer, SearchError

log = logging.getLogger(__name__)


class Searcher(Protocol):
    calls: int

    async def shopping(self, query: str) -> list[Candidate]: ...

    async def offers(self, page_token: str) -> list[Offer]: ...


class Match(BaseModel):
    id: int
    title: str
    price: float | None
    currency: str
    old_price: float | None = None
    store: str | None
    link: str | None
    google_link: str | None
    thumbnail: str | None
    rating: float | None
    reviews: int | None
    delivery: str | None
    condition: str | None = None
    category: str
    attributes: list[dict[str, str]]
    score: float
    rule_score: float
    ai_score: float | None = None
    level: str  # "same", "strong", "good", "partial"
    same_product: bool
    comparisons: list[dict[str, Any]]
    differences: list[str] = Field(default_factory=list)
    reason: str | None = None
    offers: list[Offer] = Field(default_factory=list)
    price_vs_reference: float | None = None
    page_token: str | None = None


class SearchRun(BaseModel):
    id: int | None = None
    created_at: datetime
    reference: Reference
    key_attributes: list[dict[str, str]]
    reference_specs: list[dict[str, str]] = Field(default_factory=list)  # columns for the comparison grid
    summary: str | None = None
    queries: list[str]
    matches: list[Match]
    candidates_found: int
    searches_used: int
    ai_used: bool
    demo: bool = False
    notes: list[str] = Field(default_factory=list)


def _norm_store(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower().replace(".com", ""))


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    seen: dict[str, Candidate] = {}
    for c in candidates:
        key = c.product_id or f"{re.sub(r'[^a-z0-9]', '', c.title.lower())}|{_norm_store(c.store)}"
        if key not in seen:
            seen[key] = c
        elif seen[key].price is None and c.price is not None:
            seen[key] = c
    return list(seen.values())


def _level(score: float, same: bool) -> str:
    if same:
        return "same"
    if score >= 0.75:
        return "strong"
    if score >= 0.5:
        return "good"
    return "partial"


def _key_attributes(ref: Reference) -> list[dict[str, str]]:
    return [
        {"name": label(k), "value": display_value(k, v), "importance": "normal"}
        for k, v in ref.attributes.items()
        if k not in ("brand",)
    ]


async def find_similar(
    reference: Reference,
    searcher: Searcher,
    settings: Settings,
    claude: Claude | None = None,
    demo: bool = False,
) -> SearchRun:
    notes = list(reference.notes)
    key_attrs = _key_attributes(reference)
    summary = None
    queries = build_queries(reference, settings.max_queries)
    ai_used = False

    # 1. Claude reads the reference page (optional).
    if claude is not None:
        try:
            profile = await claude.describe(
                reference.title, reference.brand, reference.url, reference.price,
                {a["name"]: a["value"] for a in key_attrs}, reference.page_text, settings.max_queries,
            )
            ai_attrs = [a for a in profile.get("attributes") or [] if isinstance(a, dict) and a.get("name")]
            if ai_attrs:
                key_attrs = [{"name": str(a["name"]), "value": str(a.get("value", "")),
                              "importance": str(a.get("importance", "normal"))} for a in ai_attrs]
            summary = profile.get("summary")
            ai_queries = [q.strip() for q in profile.get("queries") or [] if isinstance(q, str) and q.strip()]
            if ai_queries:
                # Keep our exact-title query first; Claude's spec queries follow.
                merged = [queries[0]] + [q for q in ai_queries if q.lower() != queries[0].lower()]
                queries = merged[: settings.max_queries]
            ai_used = True
        except AIError as exc:
            notes.append(f"AI matching unavailable ({exc}); used rule-based matching.")
            claude = None

    # 2. Search.
    found: list[Candidate] = []
    errors: list[str] = []
    for q in queries:
        try:
            found.extend(await searcher.shopping(q))
        except SearchError as exc:
            errors.append(str(exc))
            if "key" in str(exc).lower() or "run out" in str(exc).lower():
                break
    if not found and errors:
        raise SearchError(errors[0])
    if errors:
        notes.append(f"Some searches failed: {errors[0]}")
    candidates = _dedupe(found)

    # 3. Rule-based scoring.
    brands = {w.lower() for w in (reference.brand or "").split()}
    ref_store = _norm_store(reference.store.split(".")[0] if reference.store else None)
    scored: list[dict[str, Any]] = []
    for c in candidates:
        category, attrs = analyze(c.title, c.text())
        result = rule_score(reference.category, reference.attributes, reference.title, category, attrs, c.title, brands)
        sim = title_similarity(reference.title, c.title)
        same = same_product(reference.attributes, attrs, sim, reference.brand, c.title)
        if not same and reference.brand and reference.brand.lower() in c.title.lower():
            # Same brand, and every spec the listing states agrees with ours, covering most of them.
            ref_keys = [k for k in reference.attributes if k not in ("brand", "gtin", "part_number")]
            compared = result["comparisons"]
            if (ref_keys and compared and all(x["match"] == "yes" for x in compared)
                    and len(compared) >= max(3, round(0.75 * len(ref_keys))) and sim >= 0.6):
                same = True
        # Skip the reference listing itself (same product at the store the link came from).
        if same and ref_store and _norm_store(c.store).startswith(ref_store[:6]):
            continue
        if same:
            result["score"] = max(result["score"], 0.99)
        scored.append({"candidate": c, "category": category, "attrs": attrs, "rule": result, "same": same})

    # 4. Claude judges the most plausible results (optional).
    if claude is not None and scored:
        shortlist = sorted(scored, key=lambda s: -s["rule"]["score"])[:80]
        try:
            verdicts = await claude.judge(
                reference.title, summary or "", key_attrs,
                [{"id": i, "title": s["candidate"].title, "store": s["candidate"].store,
                  "price": s["candidate"].price, "text": s["candidate"].text()}
                 for i, s in enumerate(shortlist)],
            )
            for i, s in enumerate(shortlist):
                v = verdicts.get(i)
                if not v:
                    continue
                try:
                    s["ai"] = max(0.0, min(1.0, float(v.get("score", 0)) / 100))
                except (TypeError, ValueError):
                    continue
                s["same"] = s["same"] or bool(v.get("same_product"))
                s["differences"] = [str(d) for d in v.get("differences") or []][:6]
                s["reason"] = v.get("reason")
        except AIError as exc:
            notes.append(f"AI scoring failed ({exc}); showing rule-based scores.")

    for s in scored:
        rule = s["rule"]["score"]
        s["final"] = round(0.7 * s["ai"] + 0.3 * rule, 3) if "ai" in s else rule

    scored.sort(key=lambda s: (-s["final"], s["candidate"].price if s["candidate"].price is not None else 1e12))

    # 5. Keep good matches, and at least MIN_RESULTS overall.
    keep = [s for s in scored if s["final"] >= 0.45][: settings.max_results]
    if len(keep) < settings.min_results:
        keep = scored[: settings.min_results]
    if len(keep) < settings.min_results:
        notes.append(f"Only {len(keep)} products were found. Try adding details or a broader product name.")

    matches: list[Match] = []
    for i, s in enumerate(keep):
        c: Candidate = s["candidate"]
        diff = None
        if reference.price and c.price is not None:
            diff = round(c.price - reference.price, 2)
        matches.append(Match(
            id=i,
            title=c.title,
            price=c.price,
            currency=c.currency,
            old_price=c.old_price,
            store=c.store,
            link=c.link,
            google_link=c.google_link,
            thumbnail=c.thumbnail,
            rating=c.rating,
            reviews=c.reviews,
            delivery=c.delivery,
            condition=c.condition,
            category=s["category"],
            attributes=[{"name": label(k), "value": display_value(k, v)} for k, v in s["attrs"].items() if k != "brand"],
            score=s["final"],
            rule_score=s["rule"]["score"],
            ai_score=s.get("ai"),
            level=_level(s["final"], s["same"]),
            same_product=s["same"],
            comparisons=s["rule"]["comparisons"],
            differences=s.get("differences", []),
            reason=s.get("reason"),
            price_vs_reference=diff,
            page_token=c.page_token,
        ))

    # 6. Direct store links for the top results.
    lookups = 0
    for m in matches:
        if lookups >= settings.store_link_lookups:
            break
        if m.link or not m.page_token:
            continue
        try:
            await resolve_store_link(m, searcher)
            lookups += 1
        except SearchError as exc:
            notes.append(f"Store link lookup stopped: {exc}")
            break

    order = [r.feature for r in rules_for(reference.category, reference.attributes)]
    spec_keys = sorted((k for k in reference.attributes if k not in SKIP),
                       key=lambda k: order.index(k) if k in order else len(order))
    reference_specs = [{"feature": k, "label": label(k), "value": display_value(k, reference.attributes[k])}
                       for k in spec_keys]

    return SearchRun(
        created_at=datetime.now(timezone.utc),
        reference=reference,
        key_attributes=key_attrs,
        reference_specs=reference_specs,
        summary=summary,
        queries=queries,
        matches=matches,
        candidates_found=len(candidates),
        searches_used=searcher.calls,
        ai_used=ai_used,
        demo=demo,
        notes=notes,
    )


async def resolve_store_link(match: Match, searcher: Searcher) -> Match:
    """Fill match.link and match.offers from the product's store list."""
    if not match.page_token:
        return match
    offers = await searcher.offers(match.page_token)
    offers = [o for o in offers if o.link]
    if not offers:
        return match
    wanted = _norm_store(match.store)
    own = next((o for o in offers if wanted and _norm_store(o.store).startswith(wanted[:6])), None)
    match.link = (own or offers[0]).link
    match.offers = sorted(offers, key=lambda o: o.price if o.price is not None else 1e12)
    return match
