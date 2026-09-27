# PLAN: Read real local menus (phonetic spellings, Marathi script) + deeper Maharashtra discovery
run: local-menus · branch: prodv2.0 · base: 31bbe1c8b83d807d9a8d5ef00736de9903c58166 · created: 2026-09-27T16:50:32Z

## Requirement (verbatim)
> Hey, I hvae ran this for this new restaurant. hotel gavkari, I have given you the sheet. we are right where we were first. bro . like 50% only. items only. see the report and see what's up.

## Goal
Menus written the way local Maharashtra restaurants write them (phonetic English, Marathi/Devanagari script, glued words, look-alike letters) get the same coverage as clean English menus, with precision unchanged.

## Evidence (recon, 2026-09-27)
- Hotel Gavkari: 215 dishes, 111 ready (52%). 104 misses: 84 "Not found", 18 "Name is not in English letters", 2 uncertain.
- Hand-corrected spellings of the 85 distinct missed dishes: 58 match exact/strong from the CURRENT pool (offline, current matcher) -> spelling alone ~ +60 rows (-> ~80%).
- Misspellings seen: BATER(butter) JIRA(jeera) STIM(steam) SEZVAN(schezwan) MASHRUM(mushroom) SOYABIN(soyabean) KARI(curry) TANDURI(tandoori) HAIDRABADI(hyderabadi) CHATANI(chutney) PITAL(pitla) CRISPI/CRESPI(crispy) CRANCHI(crunchy) PIS(peas) GARLIK(garlic) KULCHCHHA(kulcha) LACHCHHA(lachha) GHI(ghee) PLET(plate) HAF/FUL(half/full) LEMAN(lemon) CORIUNDER(coriander) KHIMA(keema) KOPHTA(kofta) JAYKA(zaika) LAJVAB(lajawab) MATAKI(matki) MASUR(masoor) ROST(roast) PANNER(paneer) CHECKEN(chicken) AKHKHA(akkha). Glued: ANDAKARI, BOILANDA, GREENPIS, PANEERLAJIJ. Cyrillic look-alikes inside "PANEER CHАТРАТА".
- Devanagari rows: चिकन हंडी (हाफ), मालवाणी चिकन ड्राय हंडी, स्पेशल मटन हंडी, कंदुरी मटन हांडी, मटन कंदुरी प्लेट, चिकन थाळी, स्पे. चिकन थाळी, चिकन राजाराणी थाळी, मटन कंदुरी थाळी, व्हेज थाळी.
- Categories carry diet: "Shakahari Danka" (veg), "Nonveg Danka", "चिकन मांसाहारी राडा" (non-veg).
- Pool gaps for common dishes (Kaju Kolhapuri, Kaju Lababdar, Dahi Mutton, Mushroom Malvani, Kanduri): live search crawls generic cuisine lists for head-less dishes. Locality listings `/<city>/<locality>-restaurants/<cuisine>` and cities kolhapur/satara/sangli work (probed).

## Acceptance criteria
- AC1: Hotel Gavkari live dry run >= 80% dishes with a photo (was 52%), no drop in precision (orchestrator visual audit of every NEW pick: <= 2% wrong).
- AC2: Regression: the 6 earlier eval menus keep coverage within 1 dish of the archived reports/eval.md and no new wrong photo.
- AC3: Devanagari dish names are transliterated and matched; the sheet keeps the ORIGINAL name the vendor wrote.
- AC4: Spelling correction never changes a word the pool already knows (except curated entries), never corrects words shorter than 3 letters, and is covered by a golden table test (>= 40 misspelling -> correction pairs, >= 15 must-not-change words).
- AC5: Head-less dishes search cuisine listings chosen from their words; the seed tool can crawl locality listings.

## Contracts
```text
studio/spelling.py (S1):
  HOMOGLYPHS: dict[str, str] ; fold_homoglyphs(text: str) -> str
  DEVANAGARI_WORDS: dict[str, str] ; transliterate(text: str) -> str      # Devanagari -> Latin; non-Devanagari text unchanged
  MISSPELLINGS: dict[str, str]                                             # lowercase word -> lowercase replacement (may contain a space)
  phonetic_key(word: str) -> str
  class Speller: __init__(self, vocab: Mapping[str, int]) ; correct(self, word: str) -> str | None ; fix_text(self, text: str) -> str
studio/text.py: normalize() calls fold_homoglyphs + transliterate first; parse_dish(name, category="", description="", *, display: str | None = None)
studio/matcher.py: PoolIndex.word_counts() -> dict[str, int]   # lowercase raw words of item names -> document frequency
studio/lexicon.py: TOKEN_CUISINES: dict[str, tuple[str, ...]] (S2)
studio/zomato.py: ZomatoClient.listing(city, cuisine, locality: str = "") ; ZomatoClient.localities(city: str) -> list[str] (S2)
```

## Verify (global)
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests
.venv/Scripts/python -m compileall -q studio app.py zomato_scrapper.py tools
```

## Task DAG
| ID | Title | Deps | Write-set | Risk | Model |
|---|---|---|---|---|---|
| S1 | Spelling/script normalization + pipeline integration | - | studio/spelling.py, studio/text.py, studio/lexicon.py, studio/matcher.py, studio/pipeline.py, tests/test_spelling.py, tests/test_text.py, tests/test_pipeline.py | high | opus |
| S2 | Word-driven discovery + locality crawl | S1 | studio/lexicon.py, studio/pipeline.py, studio/zomato.py, tools/build_seed_pool.py, tests/test_zomato.py, tests/test_pipeline.py, tests/test_seed_tool.py | med | sonnet |
| DATA2 | Maharashtra-deep seed crawl, commit seed | S2 | data/seed_pool.jsonl.gz | med | orchestrator |
| EVAL2 | Gavkari + 6-menu regression, audit | DATA2 | - | - | orchestrator |

## Rollback
git revert the S1/S2/DATA2 commits on prodv2.0.
