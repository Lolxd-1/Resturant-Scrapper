# TUNE1: Calibrate the vision veto from live evidence (stop rejecting correct exact matches)
Wave: 13 · Deps: T10B · Risk: high · Model: sonnet

## Goal
Vision stops vetoing correct photos of exact/strong name matches, while still removing outlier photos and clear non-food images. Calibrated on live data measured by the orchestrator.

## Context (measured 2026-09-27 on 101 audited-correct live picks + 3 wrongly vetoed correct photos)
- `food_ok` food probability of correct photos: min 0.773, p5 0.883. A correct "Makhani Cheese Fries" photo served in a paper box scored 0.396 and was rejected by the current `>= 0.5` rule.
- `head_ok` margin (own prompt sim - best other-group sim) of correct photos: min -0.012, p5 0.001. Two correct "Paneer Takatak Sandwich" photos scored -0.028 and -0.069 and were rejected by the current `-0.02` rule; as they were the only candidates, the dish went to the owner list.
- Text gates (T06: dish head incl. item category, diet, protein, key tokens) now catch type errors like "Dum Murgh -> a pizza", so vision should mainly remove OUTLIERS among several candidates.

## Read first
- `studio/vision.py` (food_ok, head_ok, _HEAD_VETO_MARGIN)
- `studio/pipeline.py` `_Run._verify_group` (how food/head/consensus are used)
- `tests/test_vision.py`, `tests/test_pipeline.py`

## Write-set
- modify: studio/vision.py
- modify: studio/pipeline.py
- test: tests/test_vision.py
- test: tests/test_pipeline.py

## Contracts
- Add to vision.py: `FOOD_MIN_PROB = 0.30`, `HEAD_HARD_VETO = -0.10`, `HEAD_SOFT_VETO = -0.02`, `food_prob(vision, img_vecs) -> np.ndarray` (float), `head_margin(vision, img_vecs, head) -> np.ndarray` (float; +inf for all when head is None/unknown). Keep `food_ok` (now `food_prob >= FOOD_MIN_PROB`) and `head_ok` (now `head_margin >= HEAD_SOFT_VETO`) for compatibility.

## Steps
1. vision.py: implement food_prob and head_margin by refactoring the existing bodies; food_ok/head_ok become thin wrappers with the new thresholds.
2. pipeline.py `_verify_group` (vision available branch), replace the veto rule:
   - drop a candidate when food_prob < FOOD_MIN_PROB (any tier);
   - drop a candidate when head_margin < HEAD_HARD_VETO (any tier);
   - soft head veto (HEAD_SOFT_VETO <= margin is required) applies ONLY when (a) the candidate's tier is "close", or (b) at least one other candidate of the same or better tier has margin >= HEAD_SOFT_VETO (the soft veto then removes outliers only).
   - set c.type_ok = the final keep decision for the head check; c.food_ok as before.
   Do NOT modify `_combine_scores` or its TODO(human) comment (user-owned).
3. Tests with FakeVision-style controlled vectors.

## Test cases
- TC1: single exact candidate with food_prob 0.40 -> kept (was rejected).
- TC2: single exact candidate with head margin -0.05 -> kept; with -0.12 -> rejected (hard veto).
- TC3: two exact candidates, margins +0.03 and -0.05 -> only the +0.03 one kept (outlier removal).
- TC4: close-tier candidate with margin -0.03 -> rejected.
- TC5: food_prob 0.10 (logo-like) -> rejected for every tier.
- Existing tests still pass unchanged.

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_vision.py tests/test_pipeline.py tests/test_pipeline_cli.py
.venv/Scripts/python -m compileall -q studio
```

## Done when
- [ ] every test case above passes via Verify

## Out of scope
- `_combine_scores` (user-owned TODO), prompts, model choice.

## Notes
