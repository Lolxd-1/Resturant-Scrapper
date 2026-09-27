# UIFIX report

## 1. Phone layout overflow (390x844)
`studio/web/app.css`:
- `*, *::before, *::after { box-sizing: border-box; }` (was only `*`) and `html, body { max-width: 100%; overflow-x: hidden; }`.
- Added `min-width: 0` to `.field`, `.counter`, `.stats > div` so grid/flex children with text/inputs shrink instead of forcing the row wider than the viewport.
- Bottom tab bar (`.nav` inside the `@media (max-width: 900px)` sidebar rule) changed from `flex-direction: row; justify-content: space-around` to `display: grid; grid-template-columns: repeat(3, 1fr)` (matches the 3 NAV entries: New Job, History, Settings) with `min-width: 0` on each `.nav a` so "Settings" no longer clips.
- Summary counters/download wrapping and the segmented-control horizontal scroll were already correct in the existing CSS (`.counters` collapses to 1 column below 600px, `.downloads` has `flex-wrap: wrap`, `.seg` already has `overflow-x: auto`) — left unchanged.

## 2. Stray blue vertical edge lines (1440x900)
Root cause: `app.js` calls `view.focus({ preventScroll: true })` on every route change (line ~272) to move keyboard focus to `<main class="content" tabindex="-1">`. The generic rule `:focus-visible { outline: none; box-shadow: var(--focus); }` (accent-blue) then painted on `.content` itself, whose left/right edges sit at x≈248 and x≈1432 at that viewport (240px sidebar + centered 1180px max-width content) — matching the reported line positions exactly. Fixed by adding `.content:focus-visible { box-shadow: none; }` after the generic rule, so real interactive controls (buttons, inputs, the switch) keep their focus ring but the programmatically-focused container does not.

## 3. Low-disk safety
- `studio/server.py` `/api/system`: added `"free_gb"` (`shutil.disk_usage(output_dir).free`, 1 decimal).
- `studio/web/app.js` `renderSystem()`: shows an orange "Low disk space · X GB free" pill when `free_gb < 1.5`, checked before the "Ready"/engine-status branches so it takes priority.
- `studio/pipeline.py` `run_job`: after `job_dir.mkdir`, checks `shutil.disk_usage(job_dir).free`; if `< 0.5` GB, writes `job.json` with `status: "failed"` and the friendly message, and returns immediately without copying the menu or running any pipeline stage. Any `OSError` with `errno == 28` raised during a run now produces the same friendly message (instead of a raw `OSError: ...` string); `run.write_results()` in that except block is now best-effort (`try/except OSError: pass`) so a failing disk doesn't shadow the original error.
- Also hardened `_write_json`'s `os.replace` with a short bounded retry on `PermissionError` (Windows can transiently deny a rename while another handle has the file open) — this surfaced as test flakiness once `tests/test_server.py` was sped up with tighter polling.

## 4. Faster `tests/test_server.py`
Added an `autouse` `small_template` fixture (same pattern as `tests/test_pipeline.py`) that monkeypatches `pipeline.TEMPLATE_PATH` to a tiny in-memory-sized template built by `tests.test_sheets.make_template`, replacing the real 3.4 MB `data/smartbiz_template.xlsx` that openpyxl was loading on every job. Reduced the job-flow poll interval from `0.1s`/30s deadline to `0.05s`/10s deadline. Added a `free_gb` presence assertion to `test_health_and_index`. Result: `tests/test_server.py` alone runs in ~7-9s (was ~111-116s).

## 5. `tools/build_seed_pool.py` as a script
Added, before the `studio` imports: `if __package__ in (None, ""): sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`. `python tools/build_seed_pool.py --help` now exits 0.

## Tests added
- `tests/test_pipeline.py::test_uifix_tc2_low_disk_fails_before_any_work` — monkeypatches `pipeline.shutil.disk_usage` to report 0.2 GB free; asserts `run_job` marks the job failed with the disk message, and neither `results.json` nor any `*_SmartBiz_*.xlsx` output is created.
- `tests/test_server.py::test_health_and_index` — extended to assert `/api/system` returns a `float` `free_gb`.

## Verify
```
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_server.py tests/test_pipeline.py
.venv/Scripts/python tools/build_seed_pool.py --help
node --check studio/web/app.js
.venv/Scripts/python -m compileall -q studio tools
```
`orch.sh verify UIFIX` → exit 0 (33 passed).

## Self-review / concerns
- `studio/web/index.html` was in the write-set but needed no change; left untouched.
- `_combine_scores` and its `TODO(human)` in `studio/pipeline.py` were not touched.
- TC4 (headless screenshots at 390x844 / 1440x900) is orchestrator-side and not covered by the pytest Verify; the CSS/JS fixes above target the exact root causes described in the brief's context, but visual confirmation is left to the orchestrator's screenshot pass.
- The `_write_json` retry-on-`PermissionError` is a small addition beyond the literal brief steps, needed to keep `tests/test_server.py` reliably green after tightening the poll interval (Windows file-rename race under fast concurrent polling). No assertions were weakened to get there.

## Discoveries
- `data/smartbiz_template.xlsx` is 3.4 MB; loading it with openpyxl per job was the dominant cost in the old `tests/test_server.py` run time.
- The blue edge lines were a `:focus-visible` box-shadow on the app's own `<main tabindex="-1">`, triggered by `view.focus({ preventScroll: true })` on route change, not a border/outline on the sidebar or scrollbar gutter.
