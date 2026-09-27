# FIX3: Precision gates that really gate + fresh-PC runtime check (final review I2, I3, I6, M1, M2, M10)
Wave: 19 · Deps: FIX2 · Risk: high · Model: opus

## Goal
The close-tier "photos agree" gate actually rejects lone uncertain matches; a disabled OCR logo check is visible everywhere; a PC missing the Microsoft VC++ runtime gets it installed by the launcher (or a clear message) instead of silently losing vision+OCR; unrelated same-name restaurants are not treated as a chain; swaps are logo-checked; the launcher's uv is pinned.

## Context
Findings: `.orchestrator/reports/final-review.md` Important 2, 3, 6 and Minor 1, 2, 10 (read first).
Measured facts: CLIP embeddings of photos are stored per image URL in the pool DB table `embeddings` (PoolStore.get_embedding). onnxruntime's DLLs import MSVCP140.dll / MSVCP140_1.dll (VC++ 2015-2022 x64 redistributable, https://aka.ms/vs/17/release/vc_redist.x64.exe).

## Read first
- `.orchestrator/reports/final-review.md`
- `studio/vision.py` (consensus), `studio/pipeline.py` (verify close gate, source chain detection, photos BrandGuard, choose_alternate), `studio/brand.py`, `studio/sheets.py` (Summary rows), `studio/server.py` (/api/system), `app.py` (--self-test), `scripts/setup.ps1`

## Write-set
- modify: studio/vision.py
- modify: studio/pipeline.py
- modify: studio/brand.py
- modify: studio/sheets.py
- modify: studio/server.py
- modify: app.py
- modify: scripts/setup.ps1
- modify: README.md
- test: tests/test_vision.py
- test: tests/test_pipeline.py
- test: tests/test_brand.py
- test: tests/test_sheets.py
- test: tests/test_pipeline_cli.py

## Steps
1. I6: add `vision.raw_agreement(img_vecs) -> np.ndarray` = for each i, max cosine to any j != i (0.0 when n == 1). Calibrate `CLOSE_AGREE_MIN` from real data: read embeddings from the user's pool DB at `studio.config.pool_db_path()` (read-only; skip if absent) — group stored vectors by the dish they were fetched for is not possible, so instead measure on the 6 eval job dirs under `C:/Users/omkar/AppData/Local/Temp/claude/c--Users-omkar-OneDrive-Desktop-zomato-Prod-Resturant-Scrapper-main/be72c934-50cc-4414-918c-2bb0df53a6e1/scratchpad/live_out2/*/results.json` (each row has zomato_img + alternates[].zomato_img = same-dish candidates; embeddings for those URLs are in the pool DB): compute same-dish pair cosines (pick vs its alternates) and different-dish pair cosines (picks of different dishes); set CLOSE_AGREE_MIN at roughly the 20th percentile of same-dish pairs, provided it is above the 90th percentile of different-dish pairs (record both distributions in REPORT; if they overlap badly, use the midpoint and say so). Close-tier candidates are kept only when raw_agreement with another surviving candidate from a DIFFERENT restaurant >= CLOSE_AGREE_MIN (replace the `consensus >= 0.5` check). Test: lone close candidate -> needs_photo; close candidate with an agreeing photo from another restaurant -> kept.
2. I2: BrandGuard gets `available: bool` and `reason: str` (checked lazily by a cheap probe at construction: try importing rapidocr). When unavailable: add job warning "Logo check unavailable: <reason>", REPORT Summary row "Logo check: On/Unavailable", and treat it like text-only mode for brand risk: drop candidates whose restaurant is a big chain (chain_key with >= 5 restaurants) unless it is the vendor's own brand.
3. I3: app.py `--self-test` and server startup try `import onnxruntime`; failure -> /api/system status "Visual check needs the Microsoft VC++ runtime" and self-test prints the plain-English message with the link and returns 1. setup.ps1: after libraries, run `& $Py -c "import onnxruntime"`; if it fails, download https://aka.ms/vs/17/release/vc_redist.x64.exe to $HomeDir and run it with `/install /passive /norestart` (Windows shows one admin prompt; tell the user "Click Yes to install a Microsoft component"), then re-test; still failing -> Write-Host a yellow warning (the app still runs text-only). README Troubleshooting mentions it.
4. M1: a pool-only chain (no chain_outlets entity from Zomato) requires >= 3 restaurants with the same chain_key AND at least one token of the name not in brand.GENERIC; the user's own zomato_url menu is always included in the source set.
5. M2: choose_alternate runs the BrandGuard on the chosen alternate's full image; branded -> ValueError("That photo shows <brand> branding — pick another").
6. M10: pin uv in setup.ps1 to a specific release URL (use version 0.12.19 (verified 200 OK on 2026-09-27): `https://github.com/astral-sh/uv/releases/download/0.12.19/uv-x86_64-pc-windows-msvc.zip`); keep the `latest` URL only as a fallback when the pinned one 404s.

## Test cases
- TC1..TC2: close gate as in step 1.
- TC3: BrandGuard unavailable -> job summary warnings contain "Logo check unavailable", REPORT Summary shows "Logo check" "Unavailable", big-chain candidate dropped for a non-chain vendor.
- TC4: self-test with onnxruntime import monkeypatched to fail -> returns 1 and prints the VC++ link.
- TC5: pool has 3 "mirch masala" restaurants and suggest returns no chain -> vendor "Mirch Masala" is NOT treated as chain (all tokens generic? "mirch","masala" -> add both to the generic check only if they are in brand.GENERIC; if not, use vendor "Spice Kitchen" with GENERIC tokens for the test).
- TC6: choose_alternate on a branded alternate -> ValueError.
- TC7: PowerShell parse check of setup.ps1 passes.

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests
powershell -NoProfile -Command '$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path "scripts/setup.ps1"), [ref]$null, [ref]$e); if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }'
.venv/Scripts/python -m compileall -q studio app.py
```

## Done when
- [ ] every test case above passes via Verify; CLOSE_AGREE_MIN calibration numbers are in REPORT

## Out of scope
- `_combine_scores` TODO(human).

## Notes
- Commit code first, then the report. Keep turns low.
