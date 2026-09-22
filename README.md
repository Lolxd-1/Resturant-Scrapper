# Resturant-Scrapper PROD v1.0

Free pipeline that takes **any vendor's menu Excel** (dish names + prices),
finds the **best-quality photo for every dish from Zomato**, hosts the photos
on **ImageBB** (free), and fills the **Amazon SmartBiz bulk-upload sheet** —
ready to upload, zero rupees spent. Team use: 1–2 people at a time via a
Streamlit web app (free hosting).

```
YOUR MENU EXCEL
      │
      ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────────────┐
│ 1. HARVEST  │──▶│  2. MATCH  │──▶│3. DOWNLOAD  │──▶│  4. UPLOAD  │──▶│   5. BUILD   │
│ Zomato menus│   │ your dish = │   │ quality gate│   │ ImageBB   │   │ SmartBiz     │
│ + dish pics │   │ which photo?│   │ + fallback  │   │ hosting   │   │ Excel files  │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   └──────────────┘
```

## Use it (team web app — no install)

1. Open the Streamlit app URL (see Deployment below).
2. Type vendor name (SKU prefix auto-derives, editable — `HFC-001`…).
3. Upload the menu Excel. Format, row 1: `Item Name | Category | Description | Price`.
4. Paste the team ImageBB key (or the deployer saved it in app Secrets).
5. **Run pipeline** → download `*_UPLOAD_READY.xlsx` (upload to SmartBiz as-is)
   and `*_NOVEL_PENDING.xlsx` (imageless dishes — shoot real kitchen photos).
6. **Spot-check photos before uploading.** A wrong photo is worse than no photo.

## Use it (CLI, local)

```bash
pip install -r requirements.txt
set IMGBB_API_KEY=your_free_key   # https://api.imgbb.com/ (never commit this!)
python zomato_scrapper.py --menu-excel "Menu.xlsx" ^
    --template "data/smartbiz_template.xlsx" --out ./smartbiz_out ^
    --sku-prefix HFC --stage all
```

Stages run separately: `--stage harvest | match | download | build`.
Re-runs are idempotent: unchanged picks log `KEEP`, only new picks upload.

## How matching stays honest (read before onboarding a vendor)

- Word-by-word fuzzy match with spelling groups (`sev=shev`, `gobi=flower`),
  generic plural handling (`corns→corn`), size/stop words, non-veg ban,
  papad-only-papad rule, one-photo-per-dish (size variants may share).
- Coverage ≥ 0.66 and score ≥ 0.4 required, else the dish goes imageless.
- Every match run prints **POOL-GAP vs MATCHER-GAP** diagnostics per miss:
  - `POOL-GAP` → the photo pool lacks that dish family → add chain seeds,
    re-harvest, commit the new `data/pairs.json`.
  - `MATCHER-GAP` → pool has candidates but all score too low → fix
    `toks`/`STOP`/`CANON`, never lower thresholds blindly.
- `NOVEL_DISHES` starts empty; add a dish only after eye-check proves its
  auto-pick is category-wrong. `MANUAL_OVERRIDES` likewise (verify the target
  exists in `pairs.json` with a big file first).

## Onboarding a very different vendor

1. Check `CUISINE_TARGETS` covers their food (add cuisine slugs if not).
2. If their dishes live in delivery chains not yet seeded, add verified
   `/order` URLs to `CHAIN_SEEDS` (verify HTTP 200 + parseable menu first —
   guessed slugs just log `0 imaged items`).
3. Run harvest locally, eye-check risky picks, commit the refreshed
   `data/pairs.json`. The hosted app never harvests (cloud IPs get bot-walled;
   CDN + ImageBB traffic is fine).

## Deployment (Streamlit Community Cloud, $0)

1. Push this repo to GitHub (branch `prodv1.0`).
2. https://share.streamlit.io → New app → repo `Lolxd-1/Resturant-Scrapper`,
   branch `prodv1.0`, main file `app.py`.
3. App settings → Secrets: `IMGBB_API_KEY = "team-key"` (or paste per run).
4. Deploy. App sleeps after 12 h idle; anyone opening the URL wakes it.
   Limits that matter: ~1 GB RAM (this app uses far less), 1–2 concurrent
   users is fine (each run gets its own temp dir).

Why not Vercel: Hobby functions cap at 5 minutes; one vendor run needs
10–30 minutes of downloads/uploads. Serverless timeouts would kill it.

## Files

- `app.py` — Streamlit front-end (upload → run → download).
- `zomato_scrapper.py` — the pipeline (harvest → match → download → upload → build).
- `data/pairs.json` — baked photo pool (12,317 Zomato dish photos; refresh via harvest).
- `data/smartbiz_template.xlsx` — bundled SmartBiz template (or upload your own).
- `requirements.txt` — `requests`, `Pillow`, `openpyxl`, `streamlit` (all free).

## Never commit

API keys, `.streamlit/secrets.toml`, vendor menu Excels, `zcache/`,
per-run outputs (`smartbiz_out*/`, `zimages/`, results/picks JSON).
