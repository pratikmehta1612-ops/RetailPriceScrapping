# RetailPriceScrapping

Compare prices of **similar automotive products** across retailers by matching on
real specs: tire size, oil viscosity, battery group size, wiper length, bulb code
and more. Paste product links from Amazon, Walmart, Target, Best Buy or any store,
and the dashboard shows which items are true substitutes and which one is cheaper,
including per-quart pricing for fluids.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m scripts.load_demo        # optional: 10 sample products to explore
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and paste a product link.

## How it works

```
URL ─▶ fetcher ─▶ retailer adapter ─▶ feature extractor ─▶ SQLite ─▶ matcher ─▶ dashboard
       robots.txt   Amazon/Walmart/     category + specs     price      weighted
       rate limit   Target/Best Buy/    (tire size, 5W-30,   history    feature
       block check  generic JSON-LD     group H6, 22"...)               similarity
```

| Piece | File | What it does |
|---|---|---|
| Fetcher | `app/fetcher.py` | Checks robots.txt, waits between requests per site, retries 429/5xx, detects bot-check pages |
| Adapters | `app/scrapers/retailers.py` | Amazon (page selectors), Walmart (`__NEXT_DATA__`), Target and Best Buy (JSON-LD + selectors), Best Buy official API when a key is set |
| Generic parser | `app/extract/structured.py` | schema.org JSON-LD, microdata, OpenGraph and spec tables — works on most other stores |
| Features | `app/extract/automotive.py` | Detects the category and pulls normalized specs |
| Matching | `app/matching.py` | Weighted per-category similarity; a different tire size or oil viscosity caps the score at 25% |
| API + UI | `app/main.py`, `app/static/` | FastAPI JSON API and a no-build dashboard |

### Categories and the features compared

| Category | Must match | Also compared |
|---|---|---|
| Tires | size (e.g. 225/65R17), run-flat | season, load index, speed rating, LT/P type, treadwear warranty |
| Motor oil | viscosity (5W-30) | synthetic / blend / high mileage, diesel, API/ILSAC/dexos approvals |
| Batteries | group size (H6, 24F…), voltage | AGM/EFB/flooded/lithium, CCA, reserve capacity, warranty |
| Wiper blades | length | beam / hybrid / conventional |
| Headlight bulbs | bulb code (H11, 9005…) | LED/halogen/HID, lumens, color temperature |
| Brake pads | position (front/rear) | ceramic / semi-metallic / organic |
| Coolant, ATF, brake fluid | 50/50 vs concentrate, spec, DOT rating | — |

Every category also compares vehicle fitment (make and year range), pack count and title
similarity. A shared GTIN/UPC or manufacturer part number means the same item at another
store (100% match). Brand is intentionally not compared, since a cheaper brand with the
same spec is what you're looking for. Fluids are compared **per quart** and multi-packs
**per item**.

## When a site blocks the scraper

Big retailers, especially Amazon and Walmart, often answer automated requests with a
CAPTCHA. This project does **not** try to get around bot protection. Instead:

1. Open the product in your browser, **File → Save Page As… (HTML only)**.
2. In the dashboard, expand *"Site blocked the scraper? Import a saved page instead"*,
   enter the product URL and choose the saved file.

The same parsers run on the saved page, so you get identical results.

For reliable, ToS-friendly data at scale, use official APIs:

- **Best Buy Products API** — set `BESTBUY_API_KEY` in `.env`. Lookups by SKU and the
  `/api/search` endpoint then use the API. Best Buy only issues keys to company email
  addresses, not Gmail/Yahoo.
- **Amazon** — Product Advertising API 5.0 has been retired in favour of the **Creators
  API**, which requires an approved Amazon Associates account. It isn't wired in yet; the
  Amazon adapter in `app/scrapers/retailers.py` is the place to add it.

Always check each retailer's terms of use before scraping.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/products?category=&q=` | List products with latest price |
| POST | `/api/products` `{"url": ...}` | Scrape and save a product |
| POST | `/api/products/import` `{"url", "html"}` | Save from page HTML |
| GET | `/api/products/{id}` | One product |
| DELETE | `/api/products/{id}` | Remove it and its history |
| POST | `/api/products/{id}/refresh` | Re-scrape the price |
| POST | `/api/refresh` | Re-scrape everything |
| GET | `/api/products/{id}/history` | Price history |
| GET | `/api/products/{id}/similar?min_score=0.4` | Ranked substitutes with feature-by-feature comparison |
| GET | `/api/categories` | Product counts per category |
| GET | `/api/search?q=` | Best Buy search (needs API key) |

Interactive docs: http://127.0.0.1:8000/docs

## Configuration

Copy `.env.example` to `.env`. Set `REFRESH_INTERVAL_HOURS=24` to re-check prices
daily while the server runs.

## Tests

```bash
pytest
```

Tests run against synthetic product pages in `tests/fixtures/` (made-up prices), so they
need no network access.

## Ideas for next steps

- Amazon Creators API and Walmart affiliate API adapters
- Price-drop alerts (email / Slack) on top of the refresh loop
- Vehicle profile ("2019 Honda Civic") to filter by fitment
- More categories: filters by part-number cross-reference, rotors, shocks
