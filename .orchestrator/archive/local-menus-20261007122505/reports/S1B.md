# S1B report

## Implemented
- `studio/spelling.py`:
  - `DEVANAGARI_WORDS`: added नग/नग./पीस -> "pcs", मीठ/मिठ -> "mith".
  - `PROTECTED: frozenset[str]` (after `MISSPELLINGS`): curated local-word list from the brief,
    unioned with every value of `DEVANAGARI_WORDS` and every space-split token of every value
    of `MISSPELLINGS`.
  - `Speller.correct`: after the `MISSPELLINGS` lookup, returns `None` for any word in
    `PROTECTED` before falling through to `_split`/`_phonetic`.
  - `Speller.fix_text`: rewritten to process whitespace-separated segments individually. Each
    segment is checked for Devanagari characters *before* transliteration; segments that
    originated from Devanagari script only get a `MISSPELLINGS.get(word)` lookup after
    transliteration (never `_split`/`_phonetic`), while non-Devanagari segments keep using
    `self.correct` as before.
- `studio/lexicon.py`: no change needed — `NOISE` already contains `"pcs"`, verified.

## Tests added (tests/test_spelling.py)
- `test_protected_kanduri_not_phonetically_rewritten` (TC1): with vocab `{"kandhari": 50}`,
  `fix_text("कंदुरी मटन हांडी (हाफ)")` contains "kanduri" and not "kandhari".
- `test_protected_mith_not_phonetically_rewritten` (TC2): with vocab `{"meetha": 80}`,
  `fix_text("CHICKEN MITH MIRCHI") == "chicken mith mirchi"`.
- `test_devanagari_nag_becomes_pcs_not_naga` (TC3): with vocab `{"naga": 50, "anda": 20,
  "boiled": 20}`, `fix_text("ANDA BOIL (2 नग)")` tokens contain "anda" and a "boiled..." token,
  never "naga"/"nag".
- `test_protected_hangama_not_phonetically_rewritten` (TC5): with vocab `{"hungama": 50}`,
  `fix_text("VEG HANGAMA") == "veg hangama"`.
- TC4 (existing golden table, e.g. "PANEER TUPHINI"-style phonetic corrections on Latin words)
  continues to pass unmodified — verified below.

## RED (before fix, ad-hoc repro on unmodified code)
```
Speller({'kandhari': 50}).fix_text('कंदुरी मटन हांडी (हाफ)') -> 'kandhari mutton handi (half)'
Speller({'meetha': 80}).fix_text('CHICKEN MITH MIRCHI')      -> 'chicken meetha mirchi'
Speller({'hungama': 50}).fix_text('VEG HANGAMA')             -> 'veg hungama'
Speller({'naga': 50, ...}).fix_text('ANDA BOIL (2 नग)')       -> 'anda boiled (2 naga)'
```

## GREEN (after fix)
```
'kanduri mutton handi (half)'
'chicken mith mirchi'
'veg hangama'
'anda boiled (2 pcs)'
```

## Verify
`orch.sh verify S1B` -> exit 0, 199 passed
(`pytest tests/test_spelling.py tests/test_text.py tests/test_matcher.py` + `compileall studio`)

## Self-review
- Diffed against BASE: only `studio/spelling.py` and `tests/test_spelling.py` changed (plus this
  report). `studio/lexicon.py` needed no edit since `"pcs"` was already in `NOISE`.
- Confirmed `fix_text`'s per-segment transliteration is equivalent to the previous whole-text
  transliteration for whitespace-separated Devanagari runs (no cross-segment Devanagari runs
  exist in practice), so no regression for non-affected inputs.
- All prior golden pairs in `tests/test_spelling.py` (phonetic corrections on Latin words such as
  bater->butter, mashrum->mushroom) still pass, confirming phonetic correction remains available
  for non-Devanagari, non-protected words.

## Concerns
- Per the brief, `PROTECTED` includes every value of `MISSPELLINGS` (space-split), which is a
  fairly broad set (e.g. "butter", "curry", "boiled", "hara", "bhara" etc.) — this matches the
  brief's explicit instruction but means phonetic correction can never target those exact output
  words as an *input* word either. No test regressions observed.

## Discoveries
- None beyond what's in the brief; the three audited bugs (kanduri->kandhari, mith->meetha,
  नग->naga) all reproduced exactly as described on the pre-fix code and are now fixed.
