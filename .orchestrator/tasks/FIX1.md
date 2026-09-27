# FIX1: Swap/rebuild concurrency and honest downloads (final review C1, C2, I1, I7)
Wave: 17 · Deps: final review · Risk: high · Model: opus

## Goal
A photo the user rejected can never reappear in a downloaded sheet: swaps never lose each other's edits, downloads always reflect the latest swap, a failed rebuild (e.g. the sheet open in Excel) is reported instead of silently serving a stale file, and the low-disk stop can be resumed.

## Context
Findings file: `.orchestrator/reports/final-review.md` — Critical 1, Critical 2, Important 1, Important 7 (exact line numbers and repro sequences are there; read them first).

## Read first
- `.orchestrator/reports/final-review.md`
- `studio/pipeline.py` (choose_alternate, rebuild_outputs, run_job low-disk pre-check, _write_json)
- `studio/server.py` (Worker, choose_dish, _rebuild, wait_rebuild, get_job_file, zip, resume)
- `tests/test_pipeline_cli.py`, `tests/test_server.py`

## Write-set
- modify: studio/pipeline.py
- modify: studio/server.py
- modify: studio/web/app.js
- test: tests/test_pipeline_cli.py
- test: tests/test_server.py
- test: tests/test_pipeline.py

## Steps
1. Per-job lock: pipeline.py gets a module-level `job_lock(job_dir: Path) -> threading.RLock` (dict keyed by resolved path, guarded by a global lock). `choose_alternate` holds it for the whole read-modify-write of results.json/job.json (network work may stay inside; correctness beats parallel swaps). `rebuild_outputs` holds it while reading results.json/job.json and again while writing job.json. run_job holds it around each results.json/job.json write.
2. server.py `choose_dish`: return 409 {"detail": "This job is still running — wait until it finishes, then change photos."} when the worker says the job is active.
3. Generation counter: server keeps `gen[job_id]` (int) bumped on every choose; each queued rebuild records the generation it will build; after building, it clears `sheets_stale` in job.json only if `gen` is unchanged (read-modify-write under the job lock); `wait_rebuild` waits (max 90 s) until the last completed rebuild's generation >= the current generation; the shared Event must not be set by an older rebuild while a newer one is pending.
4. Failed rebuild: on exception, write `"rebuild_error": "<message>"` into job.json (PermissionError -> "Close the Excel file (<name>) and try again."). `get_job_file` and `zip` return 409 with that message when `sheets_stale` is true after waiting or `rebuild_error` is set; a successful rebuild clears rebuild_error. app.js shows the 409 message as a toast (it already toasts API errors: make sure downloads use fetch + blob or check response status so the toast appears instead of a broken file).
5. Low-disk pre-check (pipeline.py run_job): copy the menu file first (it is small), keep the original `created`, set `menu_file`, emit `{"type":"error","message": <disk message>}`; then Resume works once space is freed.

## Test cases
- TC1: two choose_alternate calls on different SKUs of the same job run concurrently (threads) with a fake fetch_full that sleeps 0.3 s for the first -> after both, results.json contains BOTH edits.
- TC2 (server): choose during an active job -> 409.
- TC3 (server): swap A then swap B quickly with a slow fake rebuild -> GET files/ready waits and the served workbook reflects B's change (P column for B empty after "needs owner photo").
- TC4 (server): monkeypatch the rebuild to raise PermissionError -> GET files/ready returns 409 with "Close the Excel file"; after a successful rebuild it returns 200.
- TC5 (pipeline): low-disk run -> job.json has menu_file set and an error event was emitted; after un-patching disk_usage, POST resume (server) or run_job again completes "done".

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_pipeline_cli.py tests/test_server.py tests/test_pipeline.py
node --check studio/web/app.js
.venv/Scripts/python -m compileall -q studio
```

## Done when
- [ ] every test case above passes via Verify

## Out of scope
- `_combine_scores` and its TODO(human) (user-owned). Other review findings (FIX2, FIX3).

## Notes
- Commit code first, then the report. Keep turns low: read only the functions named above.
