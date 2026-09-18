# Resturant-Scrapper

Free pipeline that takes a restaurant menu Excel sheet (dish names + prices),
finds the **best-quality photo for every dish from Zomato**, hosts the photos
on **ImageBB** (free), and fills the **Amazon SmartBiz bulk-upload sheet** —
ready to upload, zero rupees spent.

Built for: Gevravi Sheets (81 Maharashtrian dishes) → SmartBiz. Result: **71
dishes with eye-verified Zomato photos, 10 rare items honestly reported as
not-found** instead of filled with wrong photos.

---

## How it works (simple version)

Think of it as a 5-step factory line. Raw material (dish names) goes in one
end, finished SmartBiz Excel comes out the other:

```
YOUR MENU EXCEL
      │
      ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────────────┐
│ 1. HARVEST  │──▶│  2. MATCH  │──▶│3. DOWNLOAD  │──▶│  4. UPLOAD  │──▶│   5. BUILD   │
│ Zomato menus│   │ your dish = │   │ check size, │   │ ImageBB   │   │ SmartBiz     │
│ + dish pics │   │ which photo?│   │ make JPGs   │   │ hosting   │   │ Excel file   │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   └──────────────┘
```

### Step 1 — HARVEST (collecting Zomato photos)

- The script visits Zomato restaurant menu pages (e.g.
  `zomato.com/pune/some-restaurant/order`) for ~150 restaurants across Pune
  and Mumbai, in cuisines matching the menu (Maharashtrian, North Indian,
  Chinese, Biryani, Gujarati, …).
- Trick that makes it work: a Zomato menu page hides its **entire menu as
  JSON data inside the HTML** (`window.__PRELOADED_STATE__`). No browser
  automation, no paid API — one normal web request per page, then read the
  hidden data.
- Every menu item that has a photo gives one **(dish name → photo URL)**
  pair. Real run: **~6,500 pairs** from real restaurant menus
  (`b.zmtcdn.com/dish_photos/...`).

### Step 2 — MATCH (which photo belongs to your dish?)

- Your "Shev Bhaji" will never exactly equal Zomato's "Shev Bhaji Rassa",
  so the script compares **word by word**:
  - Spelling variants are normalised first: `sev = shev`, `flower =
    cauliflower = gobi`, `pitla = pithla = zunka`, `vengaya = onion`,
    `rassa = curry = masala`, and ~40 more groups.
  - Score = how much of YOUR dish name the Zomato item covers, minus a
    penalty for extra words (so "Paneer Masala" beats "Paneer Masala Dosa").
  - Bonus points for special words (`kala`, `jain`, `butter`, `tandoor`…).
- **Safety rules (learned the hard way):**
  - Any item with a non-veg word (chicken, mutton, egg, fish, meat…) is
    **banned** — an early version put a chicken photo on a veg dish.
  - A papad dish can only match a papad photo.
  - One photo is never reused for two dishes.
  - Dishes with no true match (Soyabean Kentucky, Kala Masala specials…)
    go to `novel_list.txt` **imageless on purpose** — a wrong photo is
    worse than no photo.

### Step 3 — DOWNLOAD (quality gate)

- Each photo is downloaded and opened: rejects under ~400px or broken
  files, converts everything to RGB JPG, shrinks giants to max 1600px.
- Then a **human eye-check**: every risky pick is viewed before it is
  accepted (this round caught and replaced 2 bad ones).

### Step 4 — UPLOAD (free hosting)

- Clean JPGs are uploaded to **ImageBB free API** → public
  `https://i.ibb.co/...` links. SmartBiz explicitly whitelists `imgbb.com`
  / `ibb.co` image URLs, which is why ImageBB was chosen.

### Step 5 — BUILD (the SmartBiz file)

- The Amazon template is copied (dropdowns/validations preserved) and each
  row is filled: SKU (`GEV-001`…), Product Name, MRP = Selling Price = your
  price, `FOOD_AND_GROCERY / Other Food and Grocery`, description, Image1 URL.
- Two files come out:
  - `smartbiz_UPLOAD_READY_71.xlsx` — only rows WITH photos. Upload as-is.
  - `smartbiz_NOVEL_PENDING_10.xlsx` — the 10 not-found dishes, pre-filled,
    waiting for real (kitchen) photos.

---

## Fallbacks — what happens when something breaks

| Problem | Fallback |
|---|---|
| Zomato blocks a page / bot-wall | Page is skipped; 150 restaurants means one loss never matters. Swiggy stayed fully blocked (empty responses) — documented, not retried forever. |
| Dish has no Zomato photo (rare/novel) | Reported in `novel_list.txt`, row left imageless. Never substituted with a wrong photo. |
| Photo too small / corrupt | Rejected at download; next-best match tried. |
| ImageBB upload hiccup (network/SSL) | Retried; local JPG copies kept in `zimages/` so nothing is ever lost. |
| Wrong match slips through | Human eye-check gate on all risky picks + `MANUAL_OVERRIDES` table for known-tricky dishes (Vengaya=onion, Zunka=Pitla…). |
| Re-running | Page cache (`zcache/`) + stage flags (`--stage match`, `--stage build`) — re-match or rebuild in seconds without re-scraping. |

Dead ends hit during research (kept here so nobody repeats them): Swiggy
`menu/pl` API (bot-walled), Zomato homepage search (bot-check page), Bing
image index (zero Zomato-CDN dish photos), Wikimedia/Openverse auto-fetch
(wrong photos: a baby for Paneer Tikka Masala, a mountain for Pitla —
automation without verification was scrapped).

## Run it

```bash
pip install -r requirements.txt
set IMGBB_API_KEY=your_free_key   # from https://api.imgbb.com/  (never commit this!)
python zomato_scrapper.py --menu-excel "Gevravi Sheets.xlsx" ^
    --template "smartbiz_bulk_upload_template_v5.xlsx" --out ./smartbiz_out --stage all
```

## Files

- `zomato_scrapper.py` — the whole pipeline (harvest → match → download → upload → build)
- `requirements.txt` — `requests`, `Pillow`, `openpyxl` (all free)
- `novel_list.txt` — the 10 dishes with no true Zomato photo
- Input Excels + API key are **yours, never committed** (see `.gitignore`)
