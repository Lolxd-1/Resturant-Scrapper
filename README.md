# Menu Studio — prod v0.1

Menu Studio turns a restaurant menu (a menu Excel, or photos of the menu) into ready-to-upload
Amazon SmartBiz sheets, with a dish photo for every item it can find on Zomato and Swiggy.
It runs as a local web app (`RUN_ME.bat`).

```
MENU PHOTOS ──▶ Gemini reads the menu ──┐   (CLI --menu-image, or the Gemini website prompt)
MENU EXCEL ─────────────────────────────┤
                                        ▼
   MATCH (photo library) ─▶ SEARCH (Swiggy dish search, then Zomato) ─▶ CHECK (vision, logo OCR, Gemini AI check)
        ─▶ PHOTOS ─▶ UPLOAD (ImgBB) ─▶ SHEETS
                                        │
   dishes with only a look-alike photo ─┴─▶ REVIEW list in the web app (approve, or search and pick)
```

## What's new in v0.1

- **Swiggy dish search** as a second photo source (one request returns 60–200 dish photos).
- **Look-alike photos**: if the exact dish has no photo, the app tries more generic names
  ("Green Chilli Paneer Pizza (Double Cheese)" → "Paneer Pizza"). These never go live on their own:
  they wait in the **Review** list until you approve them.
- **Review screen** in the job page: *Approve this photo*, *Approve all look-alikes*, or type a name,
  **Search photos** and *Use this photo*.
- **Menu photos → menu sheet with Gemini** (free tier): `zomato_scrapper.py --menu-image`, or the
  copy-paste prompt in [GEMINI_PROMPT.md](GEMINI_PROMPT.md) for the Gemini website.
- **Gemini dish helper + AI photo check** (when a Gemini key is saved): fills diet and look-alike names
  for Excel menus, and checks candidate photos — rejecting wrong dishes, watermarks, logos and text.
- Optional **Diet** and **Photo Names** columns in the menu Excel.
- Matching fixes: "Uthappa" spellings, serving words like "(Family)", "(Single Piece)", dishes whose
  type comes from the section name ("Tandoori Chicken" in "Tandoori Kebabs"), mocktails, and exact
  one-word dishes like "Palak".

Measured on real menus (live dry runs): Vithai 45/71 → 61/71 with a photo before the spelling fixes;
Hotel Rajlaxmi (286 dishes from 10 photos) → 286/286 with a photo after review (272 exact automatically).

## Use it

1. Double-click **`RUN_ME.bat`** (first time: 3–8 minutes of one-time setup).
2. In **Settings** add your **ImgBB key(s)** (free, https://api.imgbb.com/).
3. Optional but recommended — a **free Gemini API key** (https://aistudio.google.com/apikey):
   in v0.1 add it to `config\settings.json` as `"gemini_key": "<your key>"` (next to `imgbb_keys`),
   then restart the app. (A Settings field for it is coming in the next version.)
4. **New job**: type the restaurant name and upload the menu Excel
   (Item Name | Category | Description | Price, optional Diet | Photo Names).
   Have only photos? Use the Gemini website prompt ([GEMINI_PROMPT.md](GEMINI_PROMPT.md)) or the CLI below.
5. Press **Run**. When it finishes, filter **Review** to approve look-alike photos, or search and pick
   better ones for any dish. Then download the **Upload-ready sheet**.

### Menu photos from the command line

```bash
python zomato_scrapper.py --menu-image page1.jpg page2.jpg --vendor "Hotel Name" --city pune --out outputs\hotel
```

This needs `gemini_key` in `config\settings.json`. It writes `menu_extract.xlsx` (check it!) and then
runs the whole pipeline on it.

## Statuses

| Status | Meaning | What to do |
|---|---|---|
| Ready | Photo of the exact dish, checked | Nothing — it is in the UPLOAD_READY sheet |
| Review look-alike | Photo of a very similar dish | Approve it, or search and pick another |
| Needs photo | Nothing suitable found | Search with a simpler name, or ask the owner for a photo |
| Needs price | Photo found but no price | Add the price |

Review and Needs-photo dishes stay in the PENDING sheet until fixed.

## Gemini free tier — limits

The free Gemini API has a small daily quota (about 20 requests per model per day for the newest Flash
model). The app falls back across several free Flash models, caches answers, and needs roughly
2–8 requests per menu. The quota resets around **12:30 PM India time**. When it runs out, use the
Gemini website prompt. On the free tier Google may use what you send to improve its products —
menus are public, but don't send anything private.

## How accuracy works

- Exact dish first: the vendor's own Zomato menu, the local photo library, Swiggy dish search,
  then Zomato restaurant menus across many cities.
- Strict name rules (diet, protein, dish type, ingredients) decide what counts as the same dish.
- Look-alike names (from the menu sheet, Gemini, or built-in rules) are tried only when the exact dish
  has no photo — and those photos need your approval.
- Every photo is screened by CLIP vision, an OCR logo check for Zomato/Swiggy/chain branding, and —
  with a Gemini key — an AI check that also catches wrong dishes, watermarks and non-English logos.

## Troubleshooting

- **"The free Gemini quota is used up"** — wait until about 12:30 PM India time, or use the Gemini website prompt.
- **"Your Gemini key was rejected"** — create a new key at aistudio.google.com/apikey.
- **"Swiggy/Zomato is limiting requests"** — the job continues with what it found; re-run later.
- **The black window flashes and closes** — double-click `RUN_ME.bat` again; it pauses on errors.
- **"Visual check needs the Microsoft VC++ runtime"** — install https://aka.ms/vs/17/release/vc_redist.x64.exe and run `RUN_ME.bat` again.
- **Reset everything** — close the app, delete `%LOCALAPPDATA%\MenuStudio`, run `RUN_ME.bat`.

## For developers

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

- `zomato_scrapper.py` — headless CLI (`--menu-excel` or `--menu-image`).
- `tools/eval_menus.py` — dry-run a folder of menus and produce contact sheets for auditing.
- `tools/build_seed_pool.py` — rebuild the baked photo pool.
- `.orchestrator/` — the plan, task briefs and ledger of how v0.1 was built (orchestrate kit in `.claude/`).

## Never commit

- `config/` (settings and API keys), `outputs/`, `eval/`, vendor menus.
