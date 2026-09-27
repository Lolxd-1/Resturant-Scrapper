# TUNE1: Calibrate the vision veto from live evidence

## Implemented
- `studio/vision.py`: added `FOOD_MIN_PROB=0.30`, `HEAD_HARD_VETO=-0.10`, `HEAD_SOFT_VETO=-0.02`.
  Refactored `food_ok`/`head_ok` bodies into new `food_prob`/`head_margin` (raw float
  signals; `head_margin` returns +inf when head is None/unknown). `food_ok`/`head_ok`
  are now thin threshold wrappers kept for compatibility. Removed now-unused
  `_HEAD_VETO_MARGIN` constant.
- `studio/pipeline.py`: `_verify_group` now calls `food_prob`/`head_margin` directly and
  a new pure helper `_head_keep(margins, tiers)` implements the calibrated veto: hard
  veto (`margin < HEAD_HARD_VETO`) always drops; the soft veto (`margin < HEAD_SOFT_VETO`)
  only applies to "close"-tier candidates, or when at least one other same-or-better-tier
  candidate already clears the soft veto (outlier removal among several candidates).
  `c.food_ok`/`c.type_ok` set from the new thresholds. `_combine_scores` and its
  TODO(human) comment were not touched (confirmed via `git diff` — only unchanged
  context lines appear near it).

## Tests added
- `tests/test_vision.py`: `test_tune1_food_ok_uses_lowered_threshold` (food_prob 0.30
  boundary), `test_tune1_head_margin_inf_when_head_unknown`,
  `test_tune1_head_margin_matches_head_ok_threshold`.
- `tests/test_pipeline.py`: harness `_run_verify_group` builds a minimal `_Group`/
  `Candidate` set, pre-populates store embeddings (skips network fetch), and
  monkeypatches `pipeline.food_prob`/`pipeline.head_margin` to exercise `_verify_group`
  end to end. Covers TC1 (food_prob 0.40 kept), TC2 (margin -0.05 kept / -0.12
  rejected, hard veto), TC3 (two exact candidates, +0.03 kept / -0.05 outlier
  rejected), TC4 (close tier margin -0.03 rejected), TC5 (food_prob 0.10 rejected for
  exact/strong/close tiers).

## Verify
`orch.sh verify TUNE1` → exit 0, log `.orchestrator/logs/TUNE1-verify-20260927T120104Z-2716.log`
(35 passed: tests/test_vision.py, tests/test_pipeline.py, tests/test_pipeline_cli.py).
`compileall studio` clean.

## Self-review
- Only touched vision.py, pipeline.py, and the two test files (write-set).
- `_combine_scores`/TODO(human) comment unmodified.
- No new dependencies; no networking/model downloads in tests (embeddings
  pre-populated directly in the store).

## Concerns
- None.

## Discoveries
- None beyond the brief.
