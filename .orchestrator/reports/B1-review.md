# Review (task): B1
VERDICT: APPROVE
## Critical
None.
## Important
None.
## Minor
1. studio/gemini.py:~150 · two consecutive per-minute 429s on every model return reason "rate limit" with is_quota=True, so the user sees the "resets around 12:30 PM India time" message, which is wrong for a per-minute limit · misleading wording only; matches the brief literally · optional: use a separate message for per-minute exhaustion.
2. studio/gemini.py:~100 · cache key omits max_output_tokens (and model) · a smaller-token-budget call can reuse an answer generated under a different budget · optional: include it in the key blob.
3. studio/gemini.py:~108 · cache read catches only ValueError; an OSError (locked file on OneDrive/AV) would propagate instead of falling through to a request · optional: catch (OSError, ValueError).
4. studio/gemini.py:_exhausted · mutated/read outside _lock; safe under the GIL for single dict ops, and the _last_start check is locked · optional: take _lock for consistency.
5. studio/gemini.py:_error_info · `v.get` on a non-dict violation raises AttributeError (only d is isinstance-checked) · guard with isinstance(v, dict).
6. tests/test_gemini.py:51 · autouse fixture clears state and uses a constant fake clock; no test of concurrent callers or of the 5xx/network retry, 404, or high_res 400 retry paths (not required by TC1-TC11) · optional.
## Checked
- Key exposure: key only in the x-goog-api-key header (_headers); URLs are API_BASE/models/{model}:generateContent and /models?pageSize=1; log lines emit model, HTTP code, status, finishReason, token counts and type(e).__name__ only (never exception text or headers); GeminiError messages are fixed strings or Google's message[:200] (no key); cache stores only the parsed answer, and the cache key hashes inputs, not the key. TC11 and the cache assertion test this.
- Quota/fallback: per-day 429 -> _exhausted +3600 and next model; per-minute 429 -> sleep(min(delay or 20, 60)), one retry, then next model; 401/403 or 400 "api key" -> immediate GeminiError; 400 high_res retried once without mediaResolution, else error; 404 -> next; 5xx/RequestException -> sleep 5, one retry, then next; the final quota-vs-generic error split matches the brief, and all-already-exhausted gives GeminiQuotaError. The 5xx and network retries share one counter, which is acceptable.
- Thread safety: _lock guards the throttle's read-then-set of _last_start, so spacing holds across instances (the lock is held while sleeping, which serializes starts as intended); the retry sleeps are outside the lock; _exhausted accesses are single dict operations (see Minor 4).
- Finish/parse handling: thought parts skipped; non-STOP, empty, and non-dict answers go to the next model with a WARNING.
- Config/models: gemini_key is last in Settings, stripped, non-str -> ""; ai_cache_dir creates home/ai_cache; round-trip and old-file tests present.
- Tests: TC1-TC11 present, offline, and able to fail; nothing weakened. Not executed (no suite run, per instructions).
- Scope: only write-set files changed (plus .orchestrator report, excluded).
