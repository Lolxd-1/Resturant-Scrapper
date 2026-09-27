# FIX3 report

STATUS: DONE_WITH_CONCERNS
Commits: 6e39526 (I6 close gate + LPP-008), 34a508b (I2 logo check, M1 pool chains, M2 swap OCR), 2510576 (I3 VC++ runtime, M10 uv pin, README)

## Implemented
- I6: `vision.raw_agreement(img_vecs)` returns each photo's max cosine to any other photo (0.0 when there is only one). `vision.CLOSE_AGREE_MIN = 0.82`. In `_verify_group`, a close-tier candidate is kept only if keep_close holds (not strict, vision on, no exact/strong kept) AND its raw_agreement against kept candidates from OTHER restaurants is >= CLOSE_AGREE_MIN. This replaces `consensus >= 0.5`. `consensus` still feeds `_combine_scores`, which is untouched.
- LPP-008 note: candidates with source own/chain bypass the close-tier gate, and their head check is only the hard veto (`margin >= HEAD_HARD_VETO`). The food check still applies.
- I2: `BrandGuard.available` / `.reason`. When no scripted `ocr` is given, a construction-time probe imports `rapidocr` AND `onnxruntime`. Measured: `from rapidocr import RapidOCR` does NOT import onnxruntime, so probing rapidocr alone would miss the DLL failure. `_disable()` (a runtime engine failure) also flips available=False. At the end of `photos()`, an unavailable guard adds the job warning `Logo check unavailable: <reason>` and a log line. While the guard is unavailable, `_photo_group` skips options whose `chain_key(restaurant)` has >= 5 pool outlets. The vendor's own chain_key and own/chain sources are exempt. The reason when every option was skipped this way is "Only photos from <chain> found and the logo check is unavailable — ask the owner for a photo". REPORT Summary has a new row `Logo check: On/Unavailable` (`sheets.build_outputs(..., logo_on=)`). `rebuild_outputs` derives logo_on from the stored summary warnings.
- I3: `server.onnxruntime_error()`. The Worker status after engine load is `Visual check needs the Microsoft VC++ runtime` when onnxruntime can't import. `app.py --self-test` prints a message with https://aka.ms/vs/17/release/vc_redist.x64.exe and returns 1. After the libraries step, setup.ps1 test-imports onnxruntime. On failure it prints "Click Yes to install a Microsoft component", downloads vc_redist.x64.exe to $HomeDir, runs `/install /passive /norestart` with -Wait, and re-tests. If it still fails it prints a yellow warning and the app keeps running. README Troubleshooting has an entry for this.
- M1: a pool-only chain now needs >= 3 outlets AND a vendor_key token not in `brand.GENERIC`. In `source()`, outlets from an "own" menu sort first, so they are always inside `MAX_SOURCE_OUTLETS`.
- M2: after download, `choose_alternate` runs a BrandGuard built the same way as in photos (shared `_brand_guard(sizes, vendor)` helper). Branded -> `ValueError("That photo shows <brand> branding — pick another")`, and results.json is unchanged.
- M10: setup.ps1 downloads uv 0.12.19 from the pinned URL. It falls back to `releases/latest`, with fresh retries, only when the pinned URL returns 404.

## CLOSE_AGREE_MIN calibration
Source: 6 eval jobs in scratchpad/live_out2/*/results.json. Embeddings come from %LOCALAPPDATA%\MenuStudio\pool.sqlite, opened read-only.
- Same-dish pairs (pick vs alternates from a different restaurant), n=794: p10 0.787, p20 0.811, p50 0.846, p80 0.880.
- Different-dish pairs (picks of different dishes within a job), n=8188: p50 0.727, p80 0.803, p90 0.838, p95 0.862.
- The distributions overlap: same-dish p20 (0.811) is below different-dish p90 (0.838). As the brief directs, I used the midpoint, 0.8245, rounded to 0.82. At 0.82, 73.6% of same-dish pairs pass and 14.4% of different-dish pairs pass. (At 0.811 it is 79.7% / 17.3%; at 0.838 it is 58.1% / 9.9%.) Many "different-dish" pairs come from one menu with close siblings (for example, two pizzas), which inflates that tail.

## Tests added
- test_vision: `test_fix3_raw_agreement_is_best_cosine_to_another_photo` checks the values and the n=1 -> 0.0 case.
- test_pipeline: `test_fix3_tc1_lone_close_candidate_needs_photo` (TC1); `test_fix3_tc2_close_candidate_with_agreeing_photo_from_other_restaurant_kept` (TC2); `test_fix3_close_candidates_from_same_restaurant_do_not_agree`; `test_fix3_lpp008_chain_menu_match_bypasses_close_gate_and_soft_veto` (soft-veto margin kept, hard-veto margin rejected); `test_fix3_tc3_logo_check_unavailable_drops_big_chain_photos` (TC3: warning, REPORT "Logo check" = "Unavailable", big-chain photo dropped, small-restaurant dish still ready); `test_fix3_tc5_generic_same_name_pool_restaurants_are_not_a_chain` (TC5 uses "Spice Kitchen": "spice" and "kitchen" are in GENERIC, "mirch" and "masala" are not); `test_fix3_own_url_menu_always_in_source_set`. `_run_verify_group` gained an optional `rows=` parameter.
- test_brand: the guard is unavailable when rapidocr can't import; it is available when OCR is scripted.
- test_sheets: the existing summary test now also asserts Logo check = On; new test for logo_on=False -> "Unavailable".
- test_pipeline_cli: `test_fix3_tc6_choose_alternate_rejects_branded_photo` (TC6); `test_fix3_tc4_self_test_fails_with_vc_runtime_link_when_onnxruntime_cannot_load` (TC4); a worker status test with onnxruntime blocked.
- TC7: the Verify PowerShell parse check passes.

## Verify
`orch.sh verify FIX3` -> exit 0: 286 passed, the setup.ps1 parse check is clean, and compileall is clean.
I didn't run a RED phase separately. Under the old code, TC1 would keep the candidate (consensus=1.0 for n=1), TC5 would be source=chain, and the own-URL test would lose the own menu to the larger pool menu.

## Concerns
- The web UI (studio/web/app.js, outside the Write-set) shows `system.status` only while `ready` is false. After the engine loads, the VC++ status appears in /api/system but the header pill still says "Ready · N photos". Vision-unavailable is still surfaced as before.
- `choose_alternate` builds a new BrandGuard per swap. It loads all pool items and the RapidOCR engine each time, adding about 1-2 s to a swap. Caching it on Engine would be faster, but the brand words depend on the pool.
- The big-chain drop happens after the download and OCR attempt, so one full download is spent per skipped option. It sits there because the guard can become unavailable during its first OCR call.
- Overlap in the calibration data means the close gate is a moderate filter: about 14% of different-dish pairs from the same menu still reach 0.82.
- I did not change the "Combo dish" reason precedence. An own/chain combo that fails the food check or the hard veto still reports "Combo dish — ask the owner…".

## Discoveries
- Importing rapidocr doesn't load onnxruntime. The DLL failure only shows up when `RapidOCR()` is constructed or with an explicit `import onnxruntime`.
- The CLIP image embeddings in pool.sqlite are float32 and unit-norm (checked on 200 rows: 0.9999999 to 1.0000001), so the dot product in the pipeline is the cosine the calibration measured.
- scripts/setup.ps1 is checked out with CRLF (attr eol=crlf); vision.py and the other .py files are LF.
