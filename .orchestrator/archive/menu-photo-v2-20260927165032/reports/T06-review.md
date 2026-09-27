# Review (task): T06

VERDICT: CHANGES_REQUIRED

## Critical

1. `studio/matcher.py:167-169` (the `q.is_combo and not i_combo -> close` rule) · A combo menu dish can score **exact** (text 1.0) against a *different* Zomato combo item, because the downgrade only fires when the item's own name is NOT detected as a combo (`is_combo_name(item.name)` False). `is_combo_name` also returns True whenever a name simply contains two head words separated by "and"/"plus" (no literal "combo"/"meal" word needed) — so two distinct two-item combos both get `i_combo=True`, the guard never triggers, and if their token sets happen to coincide after "and"/"veg"/"half" are stripped as noise, nothing else in `_score_variant` catches it (no missing, no extra). Verified directly against the shipped code:
   ```
   q = parse_dish("Cheese Pizza (Half) & Veg Cheese Corn Pizza (Half)", "Combos")
   item = PoolItem(name="Cheese Pizza & Corn Cheese Pizza", category="Combos", diet="veg", ...)
   score(q, item, lambda t: 5.0)
   -> MatchScore(tier='exact', text=1.0, reasons=())
   ```
   This is exactly the class of bug T06 exists to close (root cause "combos" in `.orchestrator/recon/findings.md`, and independently reproduced by the orchestrator's own live-pool probe in `.orchestrator/reports/T06-orch-findings.md` item 4: "Combos must never be exact/strong"). Fix: when `q.is_combo` is true, cap the tier at "close" **regardless of `i_combo`** (per the probe's own proposed rule), not only when the item fails the combo-name heuristic. Add a golden/unit case with two distinct multi-head combos that reduce to the same token set to lock this in — no such case exists in `tests/test_matcher.py` today (only N13/N14, which cover combo-query-vs-non-combo-item and non-combo-query-vs-combo-item, not combo-vs-combo).

## Important

2. `studio/matcher.py:156-161` (close-tier evidence) · A "close" result can be produced by a single shared token when that token's idf falls below the pool median, with no minimum count of matched head/protein/base/visual tokens. The orchestrator's live-pool probe (`.orchestrator/reports/T06-orch-findings.md` item 5) found concrete false accepts at tier "close" this way: "Shevga Dry (Drumstick Dry)" -> "Veg Drumsticks" and "Soyabean Dry" -> "Soyabean Chilli" (a fried starter, resp. a Chinese dish, both visually different from the query). None of `tests/test_matcher.py`'s GOLDEN cases exercise this "too little evidence" gap, and `rank()`/`same_dish_menu_match()` both include close-tier candidates as acceptable output, so this can surface as a served photo. Consider requiring at least 2 matched non-soft/non-nonvisual tokens before tier can be "close" (as the probe suggests), with a negative golden case.

3. `studio/lexicon.py` / `studio/text.py` — three real-pool defects from the same probe file are still present and untested, though they are recall (false-negative) rather than precision issues: CURRY is still a HEADS entry (blocks "X Curry"/"X Rassa"/"X Masala" from matching each other; probe item 1), "Kala Masala" still tokenizes as ordinary visual words that block matches like "(Kala Masala Special)" vs the plain dish (probe item 2), and the lasan/lahsun/sadha/shevbhaji spelling variants aren't normalized (probe item 3). Since T06's Done-when only requires the golden set embedded in the brief (which passes), these aren't a spec violation of this brief, but they are verified live-data defects sitting in an uncommitted file (`.orchestrator/reports/T06-orch-findings.md`) clearly meant to feed back into this task or a follow-up — worth a deliberate decision (fix now vs. explicitly deferred to a named task) rather than silently left pending.

## Minor

4. `studio/matcher.py:192-193` — the "pool median idf" is recovered via `getattr(idf, "__self__", None)`, i.e. it only works when the caller passes a bound `PoolIndex.idf` method; any other callable (including the `lambda t: 5.0` used throughout the tests for cases where idf "doesn't matter") silently disables the extra-visual-token-forgiveness path. This is self-disclosed in the report and is a safe (reject-leaning) fallback, but the coupling is implicit — a docstring note on `score()` would save the next reader from rediscovering it.

## Checked
- Diff scope: `studio/matcher.py` (new), `studio/text.py`, `tests/test_matcher.py` (new), `tests/test_text.py` against BASE 4f1bb4f..HEAD. `studio/lexicon.py` in the write-set but unmodified (consistent with report).
- Contract signatures (`PoolIndex.__init__/add/idf/retrieve/__len__/item_tokens`, `score`, `rank`, `same_dish_menu_match`) match the brief exactly; tier ranges and bonuses match Step 3.
- Diet precedence rewrite in `studio/text.py` traced by hand against all 6 new `test_diet_name_decides_before_category` cases plus the existing TC9 ("Dal Fry" alone stays unknown) — correct, name-decides-first with base-token exception for the category nonveg hint, matches the T03 ruling in the brief's Notes.
- Golden set (68 cases) present verbatim from the brief; `Verify` log (`.orchestrator/logs/T06-verify-...log`) shows 103 passed, `pytest tests` (per report) 156 passed.
- Ran targeted reproductions (not the full suite) for: the combo-exact bug (Critical 1, confirmed), a hypothesized per-variant head-gate bypass via conflicting head tokens across alias variants (could not construct a clean reproduction — not reported), and near-miss protein-swapped names through `same_dish_menu_match`'s 92%-ratio fuzzy fallback (`Chicken Biryani` vs `Mutton Biryani` etc. all score well under 70, so the 92 threshold holds — not a risk).
- `retrieve()` diet pre-filter, rarest-token-first union, and head-postings cap traced against Step 4; perf numbers in the report (3.6s build, 13ms mean retrieve) are consistent with the `<60s`/`<50ms` requirements (not independently re-measured).
- No debug prints, TODOs, or unrequested scope in the diff; lexicon changes correctly reported as none.
