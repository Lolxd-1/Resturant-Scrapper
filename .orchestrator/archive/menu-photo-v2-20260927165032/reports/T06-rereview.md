# Review (rereview): T06

VERDICT: APPROVE

## Critical
(none — Critical 1 from T06-review.md resolved, see Checked)

## Important
(none — Important 2 and 3 from T06-review.md resolved, see Checked)

## Minor
(none — Minor 4 from T06-review.md resolved, see Checked)

## Checked

- Diff BASE e56b05d..HEAD 3b6d625, single commit: `studio/lexicon.py`, `studio/matcher.py`, `studio/text.py`, `tests/test_matcher.py`, `tests/test_text.py`. No unrelated files touched.

- **T06-review.md Critical 1** (combo exact/strong bypass via `not i_combo`): `studio/matcher.py:167-170` now does `if q.is_combo: tier = "close"` unconditionally (the `i_combo` unpack was dropped from `_score_variant`'s facts destructure). Reproduced the exact repro from the finding directly against the fixed code:
  `score(parse_dish("Cheese Pizza (Half) & Veg Cheese Corn Pizza (Half)", "Combos"), PoolItem(name="Cheese Pizza & Corn Cheese Pizza", category="Combos", ...), lambda t: 5.0)` -> `MatchScore(tier='close', text=0.69, reasons=('combo',))`, no longer `exact`. New test `test_combo_query_is_never_exact_or_strong` (tests/test_matcher.py:186-190) checks both this item and the original "Cheese Corn Pizza Combo" item, asserting tier=="close" and text in [0.55,0.75) — a real assertion that fails on the old code (verified: reverting just the `q.is_combo` line mentally reproduces exact/strong). `studio/lexicon.py` NON_VISUAL gained `combo, meal, platter, bucket` so the literal word "combo" in an item name doesn't itself trip the extra-visual-token reject before the combo-tier cap applies — necessary and correctly scoped companion change. `score()`'s hard gate `i_combo and not q.is_combo -> reject` (line 203-204, unrelated to this bug) is untouched and still correct.

- **T06-review.md Important 2** (close tier with too little evidence): `studio/matcher.py:171-175` adds an evidence count (matched non-soft visual/base/protein/head tokens, plus a CURRY_LIKE bonus for "Kaju Curry" vs "Kaju Masala"-style matches) and rejects "too little evidence" tiers below 2. Reproduced both probe false-accepts directly: `score(parse_dish("Shevga Dry (Drumstick Dry)"), item("Veg Drumsticks","Starters","veg"), lambda t:5.0)` -> `reject, ('too little evidence',)`; `Soyabean Dry` vs `Soyabean Chilli` -> `reject` (via the ordinary extra-visual-token path when idf is generic, and via the new evidence gate when tested through a real `PoolIndex` with `CHILLI`'s idf below median — test `test_close_needs_two_matched_tokens`, tests/test_matcher.py:191-201, builds exactly such a pool and asserts `idf("CHILLI") < median_idf()` then asserts the reject reason). Both negatives also added to GOLDEN (tests/test_matcher.py:49-50) and run through the real pool's `INDEX.idf` in `test_golden`. P27-style "Kaju Curry"/"Kaju Masala" close+ preserved (asserted `kaju.tier == "close"`).

- **T06-review.md Important 3** (CURRY-as-head, Kala Masala, spellings): all three fixed as described in `.orchestrator/reports/T06-orch-findings.md`:
  - `CURRY` removed from `HEADS`, `HEAD_GROUP`, `HEAD_PROMPT`, `HEAD_CUISINES` in `studio/lexicon.py`; `curry`/`rassa`/`gravy`/`kalwan` now canonicalize to one SOFT token `CURRY` (`saar` deliberately left alone, matching the probe's note that it's a distinct thin soup). Verified `tokens("Shevga Rassa") == tokens("Shevga Curry") == tokens("Shevga Gravy")` and `token_role("CURRY") == "soft"`. `_is_alias` (studio/text.py:171-176) gained a fallback (`"CURRY" in toks and len(toks) >= 2`) so parenthetical restatements like "(Drumstick Curry)" still alias correctly now that CURRY isn't a head — golden case "Shevga Masala Lal (Drumstick Curry)" -> "Shevga Rassa" (strong+) passes against the real pool, and `test_parenthetical_options_and_modifiers` was correctly updated (`shevga.head is None`) rather than deleted.
  - "kala" added to SOFT; combined with pre-existing "masala" SOFT membership this makes "(Kala Masala Special)" a soft-missing suffix rather than a blocker. Verified `score(parse_dish("Shev Bhaji (Kala Masala Special)","Main Course"), item("Shev Bhaji","Maharashtrian","veg"), ...)` -> `close, reasons=('missing kala','missing masala')`, matching close+.
  - Spelling synonyms added: GARLIC gained `lasan`/`lehsan`; new lowercase-canon group `"plain": ("plain","sadha","saada","sada")` (intentionally lowercase — plain stays an ordinary visual word per the finding, not a merged uppercase code); new phrases `shevbhaji`/`sevbhaji` -> `SEV BHAJI`. Verified `tokens("Lasan Methi") == tokens("Lasun Methi")`, `tokens("Sadha Rice (Full)") == tokens("Plain Rice") == tokens("Sada Rice")`, `tokens("Shevbhaji") == tokens("Shev Bhaji")`.
  - All three backed by new tests: `test_curry_family_and_spellings` (tests/test_text.py:152-160) plus 4 new GOLDEN cases (tests/test_matcher.py:86-90).

- **T06-review.md Minor 4** (idf.__self__ coupling undocumented): `score()` now has a docstring (studio/matcher.py:187-194) stating the median-idf/`__self__` coupling and its fallback behavior explicitly.

- No other consumers of `HEADS`/`HEAD_GROUP`/`HEAD_PROMPT`/`HEAD_CUISINES` exist outside `studio/lexicon.py` itself (grepped the repo) — removing `CURRY` from these dicts cannot break a crawler/prompt path elsewhere.

- Checked for regressions from the fix, not just the fixes themselves: ran the full suite, `166 passed` (up from 156 in the prior report, consistent with the added tests); ran `test_matcher.py`+`test_text.py` in isolation (113 passed) and the golden-only subset (76 passed, 17 deselected) to confirm the pre-existing GOLDEN cases still hold against the real `INDEX.idf`, not just `constant_idf`. No test was weakened — the one removed assertion (`test_soft_extra_is_strong_and_combo_query_is_close`'s combo half) was replaced by two stricter, more specific tests (`test_combo_query_is_never_exact_or_strong`, `test_close_needs_two_matched_tokens`) that assert exact score ranges/reason tuples rather than just tier.

- No debug prints, TODOs, or scope creep in the diff; `studio/lexicon.py` SOFT set correctly drops the now-dead literal `gravy`/`rassa` entries since those words are canonicalized to `CURRY` before role lookup — no leftover dead entries.
