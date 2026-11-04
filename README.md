# RetailPriceScrapping — Similar Product Finder

Give it **one reference product** (a link, a product name, or both). It reads the
product's attributes — ratings, sizes, dimensions, included parts — searches online
stores through Google Shopping, and returns **at least 10 comparable products** with
price, store, a direct link, and a feature-by-feature comparison.

Example reference: *Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16" Ball, No Shank*

| What the app reads | Value |
|---|---|
| Product type | Weight distribution hitch |
| Weight rating | 12,000 lb |
| Ball size | 2-5/16" |
| Sway control | yes |
| Bar type | round bar |
| Shank included | no |

Results with a different ball size or weight rating are pushed to the bottom, because
they aren't real substitutes. The same product at other stores is labelled **Same product**.

## 1. Get a SerpApi key (free)

1. Sign up at https://serpapi.com/users/sign_up and copy your API key.
2. In the project folder, copy `.env.example` to a new file named `.env`.
3. Open `.env` in Notepad and set `SERPAPI_API_KEY=your-key`.

The free plan has 250 searches a month. One reference product uses about **13**
(3 searches + 10 direct store-link lookups), so roughly 19 products a month. Lower
`STORE_LINK_LOOKUPS` in `.env` to stretch it; results without a link get a
**Get store link** button instead.

**Optional:** add an `ANTHROPIC_API_KEY` to let Claude read the reference page and
judge matches more like a person would (about a cent per search with the default
`claude-haiku-5-5` model). Without it the app uses its built-in rules.

## 2. Install and run (Windows with Anaconda)

Open **Anaconda Prompt** from the Start menu, then:

```bat
cd C:\Users\<you>\RetailPriceScrapping
conda create -n retailprice python=3.12 -y
conda activate retailprice
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Paste the product link and click **Find similar products**.
No key yet? Click **Try demo** to see sample results (made-up stores and prices).

Next time, only these are needed:

```bat
cd C:\Users\<you>\RetailPriceScrapping
conda activate retailprice
python -m uvicorn app.main:app --reload
```

<details><summary>Mac / Linux / plain Python</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```
</details>

## How it works

```
reference link / name
   │  read page (JSON-LD, spec tables, "Label: value" lines) or the words in the link
   ▼
attributes ── 12,000 lb · 2-5/16" ball · sway control · round bar · no shank
   │  (optional) Claude marks which attributes must match and writes searches
   ▼
3 Google Shopping searches via SerpApi ── ~40 products each, de-duplicated
   │
   ▼
score every product ── same type? hard specs equal? other specs? title overlap?
   │  (optional) Claude scores the shortlist and explains differences
   ▼
≥10 best matches ── price · store · direct link (immersive product lookup) · other stores' prices
```

Searches run three ways: the exact product, the key specs without the brand (so other
brands show up), and a broader spec search.

| File | Purpose |
|---|---|
| `app/reference.py` | Reads the reference product, falls back to the link's words if the page is blocked, builds search queries |
| `app/extract/attributes.py` | Finds measurements in any text: `12K`, `12,000 lbs GTW`, `2-5/16"`, `3 ton`, `48 x 24 x 3 in`, `150 ft-lb`, class, volts, amps… |
| `app/extract/automotive.py` | Product-type detection and type-specific specs (hitches, tires, oil, batteries, wipers, bulbs…) |
| `app/matching.py` | Weighted scoring; mismatched "must-match" specs cap the score |
| `app/ai.py` | Optional Claude reading and judging |
| `app/search/serpapi.py` | Google Shopping and store-link lookups |
| `app/finder.py` | Runs the whole search |
| `app/static/` | The web page |

Past searches are saved in `data/searches.db`, so reopening one from **Recent searches**
uses no credits.

## Tips

- **Store page blocked?** The app still works from the words in the link. You can also
  type the product name and key specs in the details box.
- **Not enough results?** Add details (e.g. `12,000 lb, 2-5/16 ball, round bar`) or use a
  broader product name.
- **Other countries:** set `SEARCH_COUNTRY` (e.g. `ca`, `gb`, `in`) in `.env`.
- Prices come from Google Shopping at search time. Check the store page before buying.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/find` `{"url", "details", "use_ai", "demo"}` | Run a search |
| GET | `/api/searches` | Recent searches |
| GET / DELETE | `/api/searches/{id}` | Open or delete a saved search |
| POST | `/api/searches/{id}/matches/{match_id}/store-link` | Look up one direct store link (1 credit) |
| GET | `/api/status` | Which keys are configured |

Interactive docs: http://127.0.0.1:8000/docs

## Tests

```bash
pytest
```

The tests replace SerpApi, Claude and the store page with fakes, so they need no keys
or internet.
