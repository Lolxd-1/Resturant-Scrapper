# UIFIX: Phone layout, stray edge lines, low-disk safety, fast server tests, runnable tools
Wave: 16 · Deps: TUNE3 · Risk: med · Model: sonnet

## Goal
The UI fits a 390 px phone without horizontal scrolling and has no visual glitches; a nearly full disk produces a clear warning instead of a crash; the server test file runs fast; `python tools/build_seed_pool.py` works as a script.

## Context (orchestrator screenshots + runs, 2026-09-27)
1. At 390x844 the New Job card, the "Find photos" button, the job summary counters and the bottom tab bar ("Settings") overflow to the right (clipped); the page must never scroll horizontally.
2. At 1440x900 thin blue vertical lines appear along the left edge of the content area (x≈248) and at the far right (x≈1432) on every view — a stray border/outline/box-shadow on the main container or scrollbar gutter.
3. A live run crashed with `OSError: [Errno 28] No space left on device` while writing results.json (the PC's C: drive was 100% full).
4. `tests/test_server.py` takes ~111-116 s (job-flow tests poll for completion; engine/template work dominates).
5. `python tools/build_seed_pool.py` fails with `ModuleNotFoundError: No module named 'studio'` (works only as `python -m tools.build_seed_pool`).

## Read first
- `studio/web/app.css`, `studio/web/app.js` (layout, tab bar, summary card, New Job card), `studio/web/index.html`
- `studio/server.py` (/api/system), `studio/pipeline.py` (run_job start, error handling)
- `tests/test_server.py`, `tools/build_seed_pool.py`

## Write-set
- modify: studio/web/app.css
- modify: studio/web/app.js
- modify: studio/web/index.html
- modify: studio/server.py
- modify: studio/pipeline.py
- modify: tools/build_seed_pool.py
- test: tests/test_server.py
- test: tests/test_pipeline.py

## Steps
1. CSS: add `*, *::before, *::after { box-sizing: border-box; }` if missing; `html, body { max-width: 100%; overflow-x: hidden; }`; ensure every grid/flex child that holds text or inputs has `min-width: 0`; inputs/selects `width: 100%`; the summary counters and download buttons wrap (`flex-wrap: wrap` / responsive grid) below 600 px; the bottom tab bar uses `display: grid; grid-template-columns: repeat(3, 1fr)` and fits 390 px; filters segmented control scrolls horizontally inside its own container (`overflow-x: auto`) instead of widening the page.
2. Find and remove the source of the vertical blue lines (inspect borders/outlines/box-shadows on the main/content/sidebar elements; a focus outline on the main container or a `border-left`/`border-right` with the accent colour are the likely causes). Keep visible focus rings for keyboard users on interactive controls only.
3. Disk safety: `studio/server.py` /api/system adds `"free_gb": float` (shutil.disk_usage of OUTPUT_DIR's drive, 1 decimal). UI sidebar status pill shows orange "Low disk space · X GB free" when free_gb < 1.5 (takes priority over "Ready"). `studio/pipeline.py`: at job start, if free space on the job dir's drive < 0.5 GB -> job status failed with error "Your computer's disk is almost full (X GB free). Free up at least 1 GB and press Resume." (no work started); any OSError with errno 28 during the job -> same friendly message as the job error (results.json best-effort).
4. tests/test_server.py: make it fast (< 30 s total) without weakening assertions: use a tiny fixture template (the pattern from tests/test_pipeline.py) and a fake engine with no live search; reduce polling intervals (e.g. 0.05 s). Add a test for /api/system free_gb presence.
5. tools/build_seed_pool.py: at the top (before `from studio import ...`) insert the repo root into sys.path when run as a script: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` guarded by `if __package__ in (None, ""):`.
6. Add tests/test_pipeline.py case: monkeypatch shutil.disk_usage to report 0.2 GB free -> run_job returns status failed with the disk message and does not create output sheets.

## Test cases
- TC1 pytest tests/test_server.py < 30 s, all passing, includes free_gb.
- TC2 low-disk run_job test as in step 6.
- TC3 `python tools/build_seed_pool.py --help` exits 0.
- TC4 (orchestrator) headless screenshots at 390x844 show no clipped content and no page-level horizontal scroll; 1440x900 shows no stray blue edge lines.

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_server.py tests/test_pipeline.py
.venv/Scripts/python tools/build_seed_pool.py --help
node --check studio/web/app.js
.venv/Scripts/python -m compileall -q studio tools
```

## Done when
- [ ] every test case above passes via Verify

## Out of scope
- `_combine_scores` and its TODO(human) (user-owned); redesigning views.

## Notes
