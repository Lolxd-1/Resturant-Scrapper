# FIX1 report

## Implemented
- pipeline.py: module-level `job_lock(job_dir) -> RLock` (keyed by resolved path). `choose_alternate` holds it for its whole read-modify-write (fetch/upload inside). `rebuild_outputs` holds it while reading results/job.json and again when writing; the write re-reads job.json, sets summary/updated, pops `rebuild_error`, and no longer touches `sheets_stale` (the server clears it). run_job's `save_job`, `_Run.write_results` and the low-disk write hold it.
- Low-disk pre-check now runs after the menu copy: keeps old `created`, sets `menu_file`, emits `{"type":"error","message":...}`.
- server.py: `choose_dish` returns 409 "This job is still running — wait until it finishes, then change photos." when active; holds the job lock across choose_alternate + `request_rebuild` so an in-flight rebuild can't clear the flag between the swap's write and the gen bump. Worker tracks `_gen` (bumped in request_rebuild) and `_built`; `_rebuild` captures gen at start, clears `sheets_stale` under the job lock only if gen is unchanged, records `rebuild_error` on failure (PermissionError -> "Close the Excel file (<name>) and try again."), and sets the event only when built >= gen. `wait_rebuild`: if stale and nothing pending (no event or event set, i.e. stale from an earlier session or a failed rebuild), rebuilds synchronously (retry path); else waits up to 90 s. `_build_lock` serialises builds. `_require_fresh_sheets` makes files/zip return 409 with rebuild_error or a "still being updated" message when stale.
- app.js: download links use `onclick: download` (fetch; on !ok toast the detail; else blob + filename from Content-Disposition).

## Files
studio/pipeline.py, studio/server.py, studio/web/app.js, tests/test_pipeline_cli.py, tests/test_server.py, tests/test_pipeline.py

## Tests
- test_fix1_tc1_concurrent_swaps_keep_both_edits: slow fetch_full swap on pizza + concurrent needs-photo on burger -> both edits survive.
- test_fix1_tc2_choose_while_job_active_is_409.
- test_fix1_tc3_download_waits_for_latest_swap: two quick swaps with slow rebuild -> served UPLOAD_READY has neither row, sheets_stale False.
- test_fix1_tc4_failed_rebuild_is_409_until_fixed: PermissionError -> files 409 "Close the Excel file (...)" and zip 409; restored rebuild -> 200, rebuild_error gone.
- test_fix1_tc5_low_disk_keeps_menu_and_resumes: menu_file set, error event, created kept, rerun completes "done".

## Verify
orch.sh verify FIX1 -> exit 0 (43 passed).

## Concerns
- rebuild_outputs no longer clears sheets_stale itself (only server used the flag). Any future caller setting the flag must clear it.
- TC3 ordering is timing-dependent against the old code (may not have failed deterministically pre-fix); it does assert the correct final state.
- A wait_rebuild retry after a failed rebuild runs the rebuild on the request thread (like the prior sync fallback).
- Pre-existing: openpyxl atexit PermissionError on temp file at interpreter exit (harmless noise).
