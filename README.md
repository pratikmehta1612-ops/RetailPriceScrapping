# RetailPriceScrapping — Similar Product Finder

Give it **one reference product** (a link, a product name, or both). It reads the
product's attributes — ratings, sizes, dimensions, included parts — searches online
stores through Google Shopping, and returns **at least 10 comparable products** with
price, store, a direct link, and a spec-by-spec comparison lined up against the reference.

Example reference: *Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16" Ball, No Shank*
→ weight rating 12,000 lb · ball 2-5/16" · sway control · round bar · no shank.
Results with a different ball size or rating drop to the bottom, the same item at other
stores is labelled **Same product**, and the cheapest real match is flagged **Lowest price**.

The app has a sign-in page. Each person has their own login, their own saved searches,
and a daily search limit, so the app can be put online safely.

---

## 1. First-time setup (Windows with Anaconda)

Open **Anaconda Prompt** from the Start menu:

```bat
cd C:\Users\<you>\RetailPriceScrapping
conda create -n retailprice python=3.12 -y
conda activate retailprice
pip install -r requirements.txt
copy .env.example .env
```

### Add your SerpApi key

1. Sign up at https://serpapi.com/users/sign_up and copy your API key.
2. `notepad .env` and set `SERPAPI_API_KEY=your-key`. Save.

The free plan has 250 searches a month. One product search uses about **13**
(3 searches + 10 direct store-link lookups), so roughly 19 a month. Lower
`STORE_LINK_LOOKUPS` in `.env` to stretch it.

Optional: set `ANTHROPIC_API_KEY` to let Claude read the page and judge matches
(about a cent per search with the default `claude-haiku-5-5` model).

### Create your login

```bat
python -m scripts.manage_users add pratik
```

It asks for a password twice (typing is hidden, at least 10 characters).

### Start the app

```bat
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and sign in.

Next time you only need:

```bat
cd C:\Users\<you>\RetailPriceScrapping
conda activate retailprice
python -m uvicorn app.main:app --reload
```

---

## 2. Adding more usernames and passwords

Run these in Anaconda Prompt, in the project folder, with `conda activate retailprice`:

| To… | Run |
|---|---|
| Add a user | `python -m scripts.manage_users add sam` |
| Change a password | `python -m scripts.manage_users passwd sam` |
| Remove a user | `python -m scripts.manage_users remove sam` |
| See all users | `python -m scripts.manage_users list` |
| Get the values to paste into a hosting service | `python -m scripts.manage_users export` |

Then **restart the app** (Ctrl+C, then start it again) for the change to take effect.

How it works:

- Users are saved in the `APP_USERS` line of `.env` as `name:hashed-password` pairs.
  Only a salted PBKDF2 hash is stored, never the password itself.
- Changing a password or removing a user signs that person out everywhere.
- Usernames aren't case-sensitive: `Pratik` and `pratik` are the same account.
- After 5 wrong passwords, sign-in is paused for 15 minutes for that username and computer.
- There's no "forgot password" email: reset it with `passwd`.

**On a hosted copy (e.g. Render):** run the command on your own computer, then run
`python -m scripts.manage_users export` and paste the `APP_USERS` value into the
host's environment settings (replace the old value). The service restarts by itself.

---

## 3. Keeping your API keys private

- Keys live only in `.env` on your computer, or in your hosting service's secret
  settings. `.env` is in `.gitignore`, so it's never pushed to GitHub. Only
  `.env.example`, which has empty values, is in the repository.
- The browser never receives a key. The page only learns *whether* search and AI are
  set up. Error messages are scrubbed so a key can't be echoed back, and the HTTP
  library's request logging (which would include the SerpApi key) is turned off.
- Every page and API call requires sign-in, except the sign-in page and `/healthz`.
  The automatic API docs pages are switched off.
- Each user only sees their own saved searches, and has a daily search limit
  (`DAILY_SEARCH_LIMIT`, default 15) so nobody can drain your SerpApi credits.
  Sample-data searches and reopening saved searches don't count.
- Links that point at private or internal network addresses are refused, so a hosted
  copy can't be used to reach the server's own network.
- Login cookies are HttpOnly and SameSite, and also Secure when served over https;
  cross-site form posts are blocked.

Before pushing, you can double-check nothing secret is tracked:

```bat
git status
git ls-files | findstr .env
```

The second command should list only `.env.example`.

If a key ever does leak, regenerate it at https://serpapi.com/manage-api-key
(and/or https://console.anthropic.com) and update `.env` or your host's settings.

---

## 4. Putting it online with Render (free plan)

1. Push the latest code to GitHub (`.env` stays on your computer).
2. On https://dashboard.render.com choose **New → Blueprint**, connect GitHub, and pick
   `RetailPriceScrapping`. Render reads `render.yaml`.
3. Render asks for the secret values. Paste:
   - `SERPAPI_API_KEY` — your key
   - `ANTHROPIC_API_KEY` — leave empty if you don't use AI
   - `APP_USERS` — the value from `python -m scripts.manage_users export`

   `SESSION_SECRET` is generated by Render automatically.
4. Create the service. When it's live, open the `onrender.com` address and sign in.

Things to know about the free plan:

- The app sleeps after 15 minutes without visitors; the first visit afterwards takes
  about a minute to wake it.
- Files are wiped on each restart or deploy, so **saved searches and daily counts reset**.
  Logins aren't affected (they live in `APP_USERS`). To keep history, add a paid
  Render disk and set `DATABASE_PATH` to a file on it (e.g. `/var/data/searches.db`).
- Check SerpApi's terms for showing its results in a hosted app.

---

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
score every product ── same type? must-match specs equal? other specs? name overlap?
   │  (optional) Claude scores the shortlist and explains differences
   ▼
≥10 best matches ── price · store · direct link · other stores' prices
```

| File | Purpose |
|---|---|
| `app/main.py` | Web server, sign-in enforcement, security headers, API |
| `app/auth.py` | Password hashing, signed session cookies, lockout |
| `scripts/manage_users.py` | Add / change / remove users |
| `app/reference.py` | Reads the reference product, builds search queries |
| `app/extract/attributes.py` | Finds measurements in any text: `12K`, `12,000 lbs GTW`, `2-5/16"`, `3 ton`, `48 x 24 x 3 in`… |
| `app/extract/automotive.py` | Product-type detection and type-specific specs |
| `app/matching.py` | Weighted scoring; mismatched must-match specs cap the score |
| `app/ai.py` | Optional Claude reading and judging |
| `app/search/serpapi.py` | Google Shopping and store-link lookups |
| `app/finder.py` | Runs the whole search |
| `app/static/` | Sign-in page and app (no build step) |
| `render.yaml` | One-click Render setup with secrets kept out of Git |

## Tests

```bash
pytest
```

The tests replace SerpApi, Claude and the store pages with fakes, so they need no keys
or internet. They also check that keys never appear in anything sent to the browser.
