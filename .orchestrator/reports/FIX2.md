# FIX2 report

## Steps -> tests

1. I5 broad exception handling (`Http.get` catches `requests.RequestException`; `parse_menu` catches `AttributeError`; `suggest` returns empty on non-dict JSON; `source()`/`search()` wrap discovery calls in `except Exception`) -> `tests/test_zomato.py::test_fix2_tc1_too_many_redirects_returns_none`, `tests/test_pipeline.py::test_fix2_tc2_suggest_value_error_still_finishes_done`.
2. I4 distinct network/http/invalid outcomes (`fetch_thumb_ex`, `fetch_full_ex`, `Http.get_ex`; pipeline only marks bad for http/invalid; `is_bad_image` ignores "network" reasons) -> `tests/test_imaging.py::test_fix2_tc3_fetch_full_ex_network_failure`, `test_fix2_tc3_fetch_full_ex_404_is_http`, `tests/test_store.py::test_fix2_tc3_is_bad_image_ignores_network_reason`.
3. M5 `used_images` updated on photo-stage fallback so two dishes never share a photo -> `tests/test_pipeline.py::test_fix2_tc4_fallback_never_reuses_another_dishs_photo`.
4. M7 menu.py category priority ("category"/"menu category"/"section" beat "type"/"group"/"course") -> `tests/test_menu.py::test_fix2_tc5_category_column_beats_type_column`.
5. M8 server `post_job` `zomato_url` validation (zoma.to -> 400; www.zomato.com accepted) -> `tests/test_server.py::test_fix2_tc6_zomato_url_validation`.
6. M9 shared `studio.config.atomic_write_text` (used by `save_settings`, `pipeline._write_json`, `server._write_json`) -> `tests/test_pipeline.py::test_fix2_tc7_atomic_write_text_retries_permission_error`.

## Implementation notes

- `Http.get` is now a thin wrapper over a new `Http.get_ex(url, params) -> (resp|None, reason)` so imaging can distinguish "network" (connection/timeout/retries exhausted) from "http" (definitive 404/410/other non-200) without changing `Http.get`'s existing return contract (all prior zomato.py tests pass unchanged).
- `imaging.fetch_thumb`/`fetch_full` are kept as thin wrappers around the new `_ex` functions per the brief.
- Removed now-unused `import os` from `studio/pipeline.py` and `studio/server.py` after routing their `_write_json` through `atomic_write_text`.

## Verify

`bash .claude/skills/orchestrate/scripts/orch.sh verify FIX2` -> 272 passed; `python -m compileall -q studio` clean.

## Concerns

- None outstanding for this task's scope.
