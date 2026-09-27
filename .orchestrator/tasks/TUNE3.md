# TUNE3: Brand guard — never put Zomato/Swiggy or another chain's branding on a vendor's storefront
Wave: 15 · Deps: TUNE2 · Risk: med · Model: sonnet

## Goal
Before a photo is chosen, local OCR reads visible text; photos showing "zomato"/"swiggy", or another chain's brand name that is not the vendor's own brand, are skipped in favour of the next candidate.

## Context (live eval 2026-09-27)
- 2 of 278 chosen photos contained a red "zomato" matchbox prop from Zomato's photo shoots (OCR read "zomato", score 0.99996). CLIP could not detect it (score overlapped clean photos).
- La Pino'z product photos contain "Pino'z" text: fine for La Pino'z itself, wrong for any other vendor.
- `rapidocr==3.9.2` works offline in the venv (bundled models, ~0.6 s init, ~1 s per image, numpy 2 compatible). It needs opencv-python 5.0.0.93, pyclipper 1.4.0, shapely 2.1.2, six 1.17.0, omegaconf 2.3.1, antlr4-python3-runtime 4.9.3, colorlog 6.12.0 (verified resolver output; already installed in .venv).
- OCR also emits junk single characters from food texture ("R", "2", "B"): only match whole brand words, never "any text".

## Read first
- `studio/pipeline.py` (_verify_group pick/alternates; photos stage fetch_full), `studio/store.py` (chain_key counts), `studio/zomato.py` (chain_key)
- `requirements.txt`

## Write-set
- create: studio/brand.py
- modify: studio/pipeline.py
- modify: requirements.txt
- test: tests/test_brand.py
- test: tests/test_pipeline.py

## Contracts
- studio/brand.py: `class BrandGuard: __init__(self, brand_words: Iterable[str], ocr=None)`; `text_in(self, jpeg: bytes) -> list[str]` (lowercased OCR words, score >= 0.6; [] when OCR unavailable); `brands_in(self, jpeg: bytes) -> set[str]`; module `ALWAYS_BLOCKED = frozenset({"zomato", "swiggy", "zomato.com"})`; `brand_words_from_pool(chain_counts: dict[str, int], min_outlets: int = 5) -> set[str]` (distinctive tokens of big chain_keys: tokens of len >= 4 minus GENERIC = {"pizza","pizzas","cafe","restaurant","burger","burgers","biryani","house","kitchen","foods","food","point","corner","express","bakery","sweets","family","dhaba","hotel","veg","pure","the","and","momos","chinese","tea","coffee","juice","shakes","center","centre","grill","bar","lounge","world","hub","junction","factory","company","station","plaza","palace","king","queen","royal","spice","taste"}); normalization of OCR text: lowercase, remove apostrophes, keep a-z0-9 words.
- OCR engine created lazily on first use (thread-safe); import failure -> guard disabled (log once), never crash.

## Steps
1. brand.py as above. `brands_in` returns ALWAYS_BLOCKED hits plus brand_words hits found as whole OCR words (after apostrophe removal, "Pino'z" -> "pinoz").
2. pipeline.py: build one BrandGuard per job: brand_words = brand_words_from_pool(counts of restaurants per chain_key in the store) minus the vendor's own chain_key tokens. In the photos stage, after fetch_full succeeds for the chosen candidate, run `brands_in(jpeg)`; if non-empty, log "Skipped a photo showing <brand> for <dish>", mark nothing bad globally (other vendors may use it), and try the next alternate (same loop as download failure). If every candidate is branded, the dish becomes needs_photo with reason "Only photos with <brand> branding found — ask the owner for a photo". Own/chain source photos skip the check for the vendor's own brand only (zomato/swiggy still blocked).
3. requirements.txt: add exactly `rapidocr==3.9.2`, `opencv-python==5.0.0.93`, `pyclipper==1.4.0`, `shapely==2.1.2`, `six==1.17.0`, `omegaconf==2.3.1`, `antlr4-python3-runtime==4.9.3`, `colorlog==6.12.0` in alphabetical position (the file is a full lock).
4. Tests use a fake OCR callable returning scripted words.

## Test cases
- TC1: fake OCR ["zomato"] -> brands_in == {"zomato"}; ["Pino'z", "Pizza"] with brand_words {"pinoz"} -> {"pinoz"}; ["R", "2", "Ketchup"] -> set().
- TC2: brand_words_from_pool({"la pinoz pizza": 12, "dominos pizza": 30, "shivraj biryani house": 1}) == {"pinoz", "dominos"}.
- TC3 (pipeline): best candidate's JPEG is "branded" (fake guard), alternate is clean -> the alternate is chosen; log mentions "Skipped a photo showing zomato".
- TC4 (pipeline): only branded candidates -> needs_photo with the branding reason.
- TC5 (pipeline): vendor "La Pino'z Pizza" with chain source photos containing "pinoz" -> kept.
- TC6: OCR import failure -> guard disabled, job still completes.

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_brand.py tests/test_pipeline.py tests/test_pipeline_cli.py
.venv/Scripts/python -m compileall -q studio
.venv/Scripts/python -c "from rapidocr import RapidOCR; print('ocr import ok')"
```

## Done when
- [ ] every test case above passes via Verify

## Out of scope
- `_combine_scores` (user-owned TODO); CLIP prompts.

## Notes
