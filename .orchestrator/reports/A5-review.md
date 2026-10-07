# Review (task): A5
VERDICT: CHANGES_REQUIRED
## Critical
(none)
## Important
1. studio/pipeline.py:967-971 · The resume path in `_photo_group` copies only local_image/image_size/hosted_url from the old row. `approved` is not carried over. verify still recomputes `lookalike=True`, so `_settle` sends an already approved and uploaded look-alike back to "review" on a re-run of the same job. `_awaits_upload` is false, so it is never re-uploaded and the user must approve it again. · Approvals are lost on resume. · Fix: in the resume branch also set `r.approved = o.approved` (and keep `o.lookalike` consistent), with a test that re-runs a job after approve_dishes.
## Minor
1. studio/pipeline.py:263-267 · `_pick_dict` has no "rung". If a look-alike pick is swapped into alternates and chosen back, `choose_alternate` sets `lookalike=False` (approved True, so the outcome is still safe). Include `rung` (and the current lookalike state) for consistency.
2. studio/pipeline.py:1115-1118 · `choose_alternate` leaves a stale `search_name` when a rung-0 alternate is chosen (lookalike False).
3. studio/pipeline.py:1205 · `approve_dishes` raises FileNotFoundError (not ValueError) if a review row's local_image is missing.
## Checked
- Rung-0 gating: `_verify_group` screening, gating and `_confident` are equivalent to the old code on the rung-0 subset. The look-alike path runs only when `kept` is empty. The no-reason branch uses `zero[0]` instead of `g.cands[0]`, which is equivalent.
- ranked_group dedupe and rung tagging, the swiggy source tag, `_swiggy_search` (cities, 300-request cap, cache, SwiggyBlocked warning once, break rules), and the Zomato part still running without Swiggy (`zomato_ok`).
- `_lookalike_kept` thresholds follow the brief (HEAD_SOFT_VETO, exact/strong only, 4 candidates, no-vision branch).
- Upload skip (`_awaits_upload`), emit filter for review rows, `_settle` review branch, summary "review", and the eval_menus.py change.
- `search_photos`: lock use, empty query error, Swiggy fallback, bad-image skip, the current photo is unchanged. `approve_dishes`: SKUs validated up front, upload errors become ValueError, partial progress persisted, sheets_stale set.
- Tests: TC1-TC7 are present and can fail, and the only removed lines are the import lines (existing tests are unedited).
- I did not re-run the suite.
