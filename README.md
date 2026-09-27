# Menu Studio

Menu Studio takes a vendor's menu Excel and turns it into ready-to-upload
Amazon SmartBiz sheets, complete with the best-quality dish photo it can find
on Zomato for every item — no photography needed for most dishes. It runs as
a local web app (`app.py`) with five stages behind the scenes:

```
YOUR MENU EXCEL
      │
      ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────────────┐
│ 1. HARVEST  │──▶│  2. MATCH   │──▶│3. DOWNLOAD  │──▶│  4. UPLOAD  │──▶│   5. BUILD   │
│ Zomato menus│   │ your dish = │   │ quality gate│   │ ImgBB      │   │ SmartBiz     │
│ + dish pics │   │ which photo?│   │ + fallback  │   │ hosting    │   │ Excel files  │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   └──────────────┘
```

## Use it

1. On the GitHub repo page, click the green **Code** button → **Download
   ZIP** → extract it somewhere convenient (a OneDrive folder or a path with
   spaces is fine).
2. Double-click **`RUN_ME.bat`**.
   - **First time:** it downloads a private Python and the libraries it
     needs, then opens Menu Studio in your browser automatically. This takes
     **3-8 minutes** and needs about **1.5 GB of free disk space** (for the
     one-time setup plus the visual-check model). Nothing is installed
     system-wide and no admin rights are required.
   - **Every time after:** it starts in a few seconds. If Menu Studio is
     already running, double-clicking again just opens it in your browser.
3. In the app: type the vendor name, upload the menu Excel, add your ImgBB
   key(s), and click **Run pipeline**.

If anything goes wrong, `RUN_ME.bat` prints a plain-English message and
waits for a key so you can read it — see **Troubleshooting** below.

## Settings: ImgBB keys

Menu Studio hosts dish photos on [ImgBB](https://api.imgbb.com/) (free)
before writing their URLs into the SmartBiz sheet.

1. Go to https://api.imgbb.com/, sign up, and copy your free API key.
2. In Menu Studio's settings, add **2-4 keys** (from your own account or
   teammates' accounts).
3. Why more than one: ImgBB free keys are rate-limited; a large menu run
   uploads many photos, and having several keys lets the app spread uploads
   across them instead of stalling on one.

## Your menu Excel

The app reads whichever columns exist and figures out the closest match to:

| Column | Notes |
| --- | --- |
| Item Name | required |
| Category | maps to the SmartBiz Product Category |
| Description | optional |
| Price | optional — blank prices are fine, the dish still gets matched and photographed |

Headers are matched flexibly (e.g. "Dish", "Item", "Product Name" all work
for the name column), so you rarely need to rename anything before
uploading.

## What you get

After a run, in `outputs/<job>/` you get:

- **`*_SmartBiz_UPLOAD_READY.xlsx`** — dishes with a confirmed photo,
  formatted for direct SmartBiz bulk upload.
- **`*_SmartBiz_PENDING.xlsx`** — dishes the app could not confidently
  photograph (no price, no safe photo match, etc.) — fill these in by hand.
- **Photo Report + owner checklist** — a page listing every matched photo
  next to the dish name, so the restaurant owner can eyeball and approve (or
  flag) picks before anything goes live.

## How accuracy works

- The app first tries the vendor's **own Zomato listing and any known chain
  menus**, then falls back to a **whole-Zomato live search across ~20
  cities** for the same dish.
- Matching uses strict rules (word-by-word fuzzy matching, category checks,
  non-veg/veg safety, one photo per dish) so a look-alike dish from a
  different cuisine is not picked by accident.
- Every candidate photo also goes through a **visual check** (and an OCR
  brand guard that skips any photo showing a Zomato, Swiggy, or other
  delivery-chain logo).
- The app **never guesses a wrong photo on purpose** — if it isn't
  confident, the dish goes to the `_PENDING` sheet and the owner checklist
  instead of getting a bad photo.

## Troubleshooting

- **The black window flashes and closes** — double-click `RUN_ME.bat` again;
  it now pauses on every failure so you can read the message. If it still
  closes instantly, run it from a Command Prompt (`RUN_ME.bat`) to see the
  full output.
- **"Port busy" / app won't start** — another program is using the port;
  close it and double-click `RUN_ME.bat` again.
- **No internet during the first run** — the one-time setup needs to
  download Python and libraries (~400 MB) plus a visual-check model
  (~600 MB); connect to the internet and try again.
- **Antivirus warnings** — the setup script downloads `uv` (a small,
  official Python installer tool) from GitHub; if your antivirus blocks it,
  allow `scripts\setup.ps1` and `RUN_ME.bat`, or ask IT to allowlist them.
- **"Zomato is limiting requests"** — Zomato is rate-limiting this network;
  wait a while and re-run, or try from a different connection.
- **Reset everything** — close the app, delete the folder
  `%LOCALAPPDATA%\MenuStudio`, and double-click `RUN_ME.bat` again for a
  clean first-time setup.

## For developers

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

CLI usage (no web UI):

```bash
python zomato_scrapper.py --menu-excel "Menu.xlsx" --vendor "Vendor Name" ^
    --sku-prefix HFC --out ./outputs
```

Other tools:

- `tools/build_seed_pool.py` — crawl Zomato and (re)build the baked photo
  pool used for offline matching (`--crawl`, `--cities`, `--cuisines`,
  `--export`).
- `tools/eval_menus.py` — run the pipeline against a folder of real menu
  Excels and report per-dish accuracy, used to catch regressions before a
  release.

## Never commit

- `config/` (local settings, API keys)
- `outputs/` (per-run results)
- vendor menu Excels
