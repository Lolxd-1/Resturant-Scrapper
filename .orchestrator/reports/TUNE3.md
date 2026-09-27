# TUNE3 report

## Implemented
- `studio/brand.py` (new): `BrandGuard` (lazy RapidOCR, thread-safe, disables itself and logs once on
  import/inference failure, never raises), `ALWAYS_BLOCKED = {"zomato", "swiggy", "zomato.com"}`,
  `brand_words_from_pool(chain_counts, min_outlets=5)` (distinctive tokens len>=4 of GENERIC-filtered
  chain names), `text_in`/`brands_in`. `ocr` constructor arg is `Callable[[bytes], list[str]]` (raw
  recognized texts, already score-filtered) — tests inject this; the default path builds a real
  `RapidOCR()` lazily and keeps only texts with score >= 0.6.
- `studio/pipeline.py`: builds one `BrandGuard` per job in `photos()` from
  `brand_words_from_pool(_chain_sizes(store.all_items()))` minus the vendor's own tokens
  (`brand_words_from_pool({vendor_key: 1}, min_outlets=0)`). In `_photo_group`, after `fetch_full`
  succeeds for a candidate, `brands_in(jpeg)` is checked; a hit logs
  "Skipped a photo showing `<brand>` for `<dish>`" and moves to the next alternate without marking the
  image globally bad. If every candidate is branded, the dish's reason becomes
  "Only photos with `<brand>` branding found — ask the owner for a photo" (settles to `needs_photo`).
- `requirements.txt`: added `rapidocr==3.9.2` and its 7 pinned deps in alphabetical position.

## Tests
- `tests/test_brand.py` (new): TC1 (blocked/brand-word/junk-word matching via a scripted fake OCR
  callable), TC2 (`brand_words_from_pool` keeps only big-chain distinctive tokens), plus
  `ALWAYS_BLOCKED` contents and an OCR-unavailable smoke check.
- `tests/test_pipeline.py`: added TC3 (branded best candidate falls back to a clean alternate; log
  message asserted), TC4 (every candidate branded -> `needs_photo` with the branding reason), TC5
  (vendor "La Pino'z Pizza" sourced via `chain`, photo contains "Pino'z" text -> kept because it's the
  vendor's own brand), TC6 (rapidocr import made to raise via `monkeypatch.setitem(sys.modules, ...)`
  -> guard disables itself, job still completes and photo is used). TC3/TC4 use real branded JPEGs
  (noise background + drawn brand text) run through the actual RapidOCR engine, not a fake, for a
  true integration check; TC5/TC6 run the full `run_job` pipeline end-to-end.

## Verify
```
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_brand.py tests/test_pipeline.py tests/test_pipeline_cli.py
.venv/Scripts/python -m compileall -q studio
.venv/Scripts/python -c "from rapidocr import RapidOCR; print('ocr import ok')"
```
33 passed, exit 0 (`orch.sh verify TUNE3`).

## Self-review
- Diff to `studio/pipeline.py` is limited to: one import line, guard construction at the top of
  `photos()`, and the branded-skip branch inside `_photo_group`'s existing option loop (no
  reformatting of surrounding code, `_combine_scores` untouched).
- Verified `_chain_sizes` reuse (no new counting logic duplicated) and that the guard is built fresh
  in `photos()` (after `source`/`match`/`search` have populated the store) rather than in `__init__`,
  so newly-fetched live-search restaurants count toward `brand_words_from_pool`.
- Confirmed existing pipeline tests (20) still pass unchanged with the real OCR engine wired in (no
  false positives on the plain noise-JPEG fixtures used elsewhere in the suite).

## Concerns
- None outstanding. A full `tests/` run (not just the brief's Verify set) was still executing in the
  background when this report was written; it was not required by the brief's Verify block and the
  targeted suite (test_brand, test_pipeline, test_pipeline_cli) is green.

## Discoveries
- `env.pool()` in `tests/test_pipeline.py` always passes `chain_key=""` to the in-memory `PoolItem`;
  the real `chain_key` used for chain-size counting only ever comes from the DB (`chain_key(name)`
  computed at `upsert_menu`), which is what made TC5 possible without touching the harness.
- RapidOCR's default bitmap font renders very small; test fixtures need a scaled TrueType font
  (`arial.ttf`, already present on this Windows box) to reliably OCR short brand words like "Pino'z".
