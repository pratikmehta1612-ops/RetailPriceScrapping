"""Optional Claude-powered reading and matching (used when ANTHROPIC_API_KEY is set).

Two calls per search:
1. describe(): reads the reference page and returns its key attributes, which
   ones must match, and better search queries.
2. judge(): scores every found product against the reference like a person
   comparing listings would, and explains the differences.

Everything degrades to the rule-based matcher if a call fails.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AIError(Exception):
    pass


def _json_from(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise AIError("Claude didn't return JSON.")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AIError("Claude returned malformed JSON.") from exc


DESCRIBE_PROMPT = """You help find products that are equivalent to a reference product, across online stores.

Reference product
Title: {title}
Brand: {brand}
Store page: {url}
Price: {price}
Attributes found by a parser: {attributes}

Page text and user notes (may be partial or noisy):
<page>
{page_text}
</page>

Return only JSON:
{{
  "product_type": "short generic name, e.g. 'weight distribution hitch'",
  "summary": "one sentence describing what the product is and what defines a substitute",
  "attributes": [
    {{"name": "Gross trailer weight rating", "value": "12,000 lb", "importance": "must"}},
    ...
  ],
  "queries": ["{n} different Google Shopping queries"]
}}

Rules:
- List the 4-10 attributes a buyer would compare: ratings, sizes, dimensions, compatibility, included parts, materials.
- importance: "must" if a different value means it's not a substitute, "high" if it matters a lot, "normal" otherwise.
- Use only facts from the title, attributes or page text. Don't invent values.
- Queries: first the exact product, then brand-free searches built from the key specs so other brands show up."""

JUDGE_PROMPT = """Compare each found product with the reference and score how good a substitute it is.

Reference: {title}
What it is: {summary}
Key attributes:
{attributes}

Found products (id, title, store, price, extra text):
{candidates}

Return only a JSON array, one object per found product:
[{{"id": 0, "score": 0-100, "same_product": true|false, "differences": ["short note", ...], "reason": "max 15 words"}}]

Scoring:
- 90-100: same product (any store), or identical specs from another brand.
- 70-89: same type, all "must" attributes match, minor differences.
- 40-69: same type but a "high" attribute differs or is unknown.
- 0-39: a "must" attribute differs, or a different kind of product or an accessory/part.
- Judge only from the information given; when a title doesn't state an attribute, say so in differences and don't assume it matches."""


class Claude:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient):
        self.api_key = api_key
        self.model = model
        self.client = client
        self.input_tokens = 0
        self.output_tokens = 0

    async def _ask(self, prompt: str, max_tokens: int) -> str:
        try:
            resp = await self.client.post(
                API_URL,
                headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"},
                json={"model": self.model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
                timeout=120,
            )
        except httpx.HTTPError as exc:
            raise AIError(f"Couldn't reach the Claude API: {exc}") from exc
        if resp.status_code >= 400:
            try:
                message = resp.json().get("error", {}).get("message", resp.text[:200])
            except ValueError:
                message = resp.text[:200]
            raise AIError(f"Claude API error {resp.status_code}: {message}")
        data = resp.json()
        usage = data.get("usage") or {}
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")

    async def describe(self, title: str, brand: str | None, url: str | None, price: float | None,
                       attributes: dict[str, str], page_text: str | None, n_queries: int) -> dict:
        prompt = DESCRIBE_PROMPT.format(
            title=title, brand=brand or "unknown", url=url or "n/a",
            price=f"${price:,.2f}" if price else "unknown",
            attributes=json.dumps(attributes) if attributes else "none",
            page_text=(page_text or "(not available)")[:10000], n=n_queries,
        )
        data = _json_from(await self._ask(prompt, 1500))
        if not isinstance(data, dict):
            raise AIError("Unexpected reply from Claude.")
        return data

    async def judge(self, title: str, summary: str, attributes: list[dict], candidates: list[dict]) -> dict[int, dict]:
        attr_lines = "\n".join(
            f"- {a.get('name')}: {a.get('value')} ({a.get('importance', 'normal')})" for a in attributes
        ) or "- (none listed; use the title)"
        results: dict[int, dict] = {}
        for start in range(0, len(candidates), 40):
            batch = candidates[start:start + 40]
            lines = "\n".join(
                f"{c['id']}. {c['title']} | {c.get('store') or '?'} | "
                f"{'$%.2f' % c['price'] if c.get('price') is not None else '?'} | {c.get('text', '')[:160]}"
                for c in batch
            )
            prompt = JUDGE_PROMPT.format(title=title, summary=summary or title, attributes=attr_lines, candidates=lines)
            data = _json_from(await self._ask(prompt, 4000))
            if not isinstance(data, list):
                raise AIError("Unexpected reply from Claude.")
            for row in data:
                try:
                    results[int(row["id"])] = row
                except (KeyError, TypeError, ValueError):
                    continue
        return results
