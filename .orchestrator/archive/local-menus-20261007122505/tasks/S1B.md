# S1B: Stop phonetic correction from rewriting real local food words
Wave: 1b · Deps: S1 · Risk: high · Model: sonnet

## Goal
The speller never turns a genuine Marathi/local dish word into a different dish: words that came from Devanagari script and a protected list of local food words are only changed by the curated MISSPELLINGS table, never by phonetic/fuzzy correction.

## Context
Orchestrator audit of every correction on the real Hotel Gavkari menu (74 names changed; ~71 correct). Wrong ones:
- "कंदुरी मटन हांडी" -> "kandhari mutton handi" (kanduri = Marathi mutton feast dish; kandhari = different dish)
- "CHICKEN MITH MIRCHI" -> "chicken meetha mirchi" (mith = salt; meetha = sweet)
- "ANDA BOIL (2 नग)" -> "anda boiled (2 naga)" (नग = pieces, a quantity word)

## Read first
- `studio/spelling.py` (Speller.correct, fix_text, DEVANAGARI_WORDS, MISSPELLINGS), `studio/lexicon.py` (NOISE), `tests/test_spelling.py`

## Write-set
- modify: studio/spelling.py
- modify: studio/lexicon.py
- test: tests/test_spelling.py

## Steps
1. spelling.py `PROTECTED: frozenset[str]` of local words that must never be phonetically corrected (lowercase): kanduri, mith, vajadi, sukka, tambda, pandhra, rassa, kala, kolhapuri, malvani, gavran, gavkari, danka, rada, timepas, akkha, zunka, pithla, pitla, bharit, usal, misal, amti, varan, solkadhi, kombdi, machhi, bhakri, bhakar, thecha, khichadi, sabudana, shengdana, kakdi, harbhara, rajarani, chatpata, lajij, chilimili, hangama. Every VALUE of DEVANAGARI_WORDS and every VALUE of MISSPELLINGS (split on spaces) is also treated as protected.
2. `Speller.correct`: after the MISSPELLINGS lookup, return None for protected words (no split, no phonetic).
3. fix_text: words produced by Devanagari transliteration (i.e. the input text contained Devanagari and the word came from a Devanagari segment) get ONLY the MISSPELLINGS lookup — never split/phonetic. Implement by transliterating per whitespace-separated segment and remembering which segments were Devanagari.
4. DEVANAGARI_WORDS: add नग -> "pcs", नग. -> "pcs", पीस -> "pcs", मीठ/मिठ -> "mith". lexicon NOISE already has "pcs" (verify) so it disappears from tokens.
5. Revert the effect for "hangama": do not map it to "hungama" (protected).

## Test cases
- TC1: fix_text("कंदुरी मटन हांडी (हाफ)") contains "kanduri" and not "kandhari" (with a vocab where "kandhari" has df 50).
- TC2: fix_text("CHICKEN MITH MIRCHI") == "chicken mith mirchi" (vocab has "meetha" df 80).
- TC3: fix_text("ANDA BOIL (2 नग)") -> tokens of the result contain EGG/anda and BOILEDEGG or boiled, and no "naga".
- TC4: every existing golden pair in tests/test_spelling.py still passes (e.g. "PANEER TUPHINI" -> "paneer toofani" is phonetic on a LATIN word and stays allowed).
- TC5: fix_text("VEG HANGAMA") == "veg hangama".

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_spelling.py tests/test_text.py tests/test_matcher.py
.venv/Scripts/python -m compileall -q studio
```

## Done when
- [ ] every test case above passes via Verify

## Out of scope
- Discovery (S2); `_combine_scores` TODO(human).
