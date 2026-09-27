# FIX2: Robustness — no job aborts on odd pages, no permanent blacklisting from Wi-Fi blips (final review I4, I5, M5, M7, M8, M9)
Wave: 18 · Deps: FIX1 · Risk: med · Model: sonnet

## Goal
Unexpected Zomato responses degrade gracefully instead of aborting a job; transient network failures never permanently remove good photos; duplicate photos and column mix-ups are prevented; OneDrive/antivirus file locks don't break saves.

## Context
Findings: `.orchestrator/reports/final-review.md` Important 4, Important 5, Minor 5, 7, 8, 9 (read them first; line numbers there).

## Read first
- `.orchestrator/reports/final-review.md`
- `studio/zomato.py` (Http.get except clause, suggest, parse_menu), `studio/imaging.py` (fetch_thumb, fetch_full), `studio/store.py` (mark_bad_image, is_bad_image), `studio/pipeline.py` (source, search, verify/photos marking, used_images, _write_json), `studio/menu.py` (role synonyms), `studio/server.py` (post_job, settings save), `studio/config.py` (save_settings)

## Write-set
- modify: studio/zomato.py
- modify: studio/imaging.py
- modify: studio/store.py
- modify: studio/pipeline.py
- modify: studio/menu.py
- modify: studio/server.py
- modify: studio/config.py
- test: tests/test_zomato.py
- test: tests/test_imaging.py
- test: tests/test_store.py
- test: tests/test_pipeline.py
- test: tests/test_menu.py
- test: tests/test_server.py

## Steps
1. I5: `Http.get` catches `requests.RequestException` (all of them) in the retry loop; `parse_menu` also catches AttributeError; `suggest` returns empty on non-dict JSON; pipeline `source()` wraps the whole vendor lookup and `search()` wraps each cached(...) discovery call in `except Exception as e: log.warning(...); continue` (ZomatoBlocked handling unchanged).
2. I4: imaging returns a distinct outcome for network failure: add `fetch_thumb_ex(url, http) -> tuple[bytes | None, str]` and `fetch_full_ex(...) -> tuple[result | None, str]` where the reason is "network" (Http.get returned None after retries / exception), "http" (non-200), "invalid" (undecodable / validate_photo failed); keep the old functions as wrappers. Pipeline calls `store.mark_bad_image` ONLY for "http"/"invalid". store.is_bad_image additionally ignores marks whose reason starts with "network" (defensive, for old DBs) — reasons are stored as given.
3. M5: when the photos stage falls back to an alternate (brand guard or download failure), update `used_images` so two different dishes don't end up sharing a photo; if the alternate is already used by another base dish, skip it.
4. M7: menu.py role priority — "category", "menu category", "section" beat "type", "group", "course" when both columns exist (a "Type" Veg/Non-Veg column left of "Category" must not become the category).
5. M8: server `post_job` validates `zomato_url`: accept "" or URLs whose host is zomato.com/www.zomato.com (add https:// when missing); `zoma.to` short links -> 400 "Open the link in your browser and paste the full zomato.com address".
6. M9: one shared helper `studio.config.atomic_write_text(path, text)` (tmp + os.replace with retries for ~2 s on PermissionError) used by save_settings, pipeline._write_json and any server json write.

## Test cases
- TC1: Http.get with TooManyRedirects raised every time -> returns None (no exception).
- TC2: fake client whose suggest raises ValueError -> run_job finishes "done".
- TC3: fetch_full network failure -> image NOT marked bad; 404 -> marked bad.
- TC4: two dishes, first's best photo fails brand/download so it falls back to the image the second dish already uses -> they end with different images (or the second best).
- TC5: menu with columns [Item Name, Type, Category, Price] -> category values come from "Category".
- TC6: post_job with "zoma.to/abc" -> 400 with the message; "www.zomato.com/pune/x" -> accepted.
- TC7: atomic_write_text survives two PermissionErrors then succeeds (monkeypatched os.replace).

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests
.venv/Scripts/python -m compileall -q studio
```

## Done when
- [ ] every test case above passes via Verify

## Out of scope
- `_combine_scores` TODO(human); FIX1/FIX3 items.

## Notes
- Commit code first, then the report. Keep turns low.
