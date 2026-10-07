# LEDGER (append-only, one line per event)
<!-- format: - <UTC time> <event>. Rulings: "Ruling: <decision> — <why> — <cost if wrong>" -->
- 2026-10-07T12:25:05Z init run=photo-to-sheet branch=main base=34439a2
- 2026-10-07T12:33:41Z wave1 parallel: write-sets disjoint, no hot files, hermetic pytest, absolute venv path, no editable install -> parallel OK (width 3)
- 2026-10-07T12:33:41Z Ruling: user chose Gemini free tier + manual Gemini-website prompt (Both); look-alikes need approval in a Review list — from AskUserQuestion — cost if wrong: rework of B milestone only
- 2026-10-07T12:34:13Z Ruling: orch-* agent types not loaded in this session (installed mid-session) -> dispatch general-purpose pinned to model sonnet with orch-executor.md as rules — cost if wrong: executor may drift from rules; gate still enforces scope/verify
- 2026-10-07T12:44:31Z wave1 merged: A1 A2 A3 gate PASS, verify-all 421 passed 2 skipped. A3 note: city lat/lng approximations accepted (city centres). dispatch A4
- 2026-10-07T12:50:56Z A4 PASS (one assertion extended to include review status — legit). dispatch A5 (opus)
- 2026-10-07T12:54:26Z planned milestone B (B1-B4) + EVAL; prompts.py authored by orchestrator (data), committed before B2/B3
- 2026-10-07T12:57:21Z recon on eval menus: rung-0 exact/strong Vithai 50\/71, Food Junction 80\/89, Hard_Pending 56\/226. Found: uthappa synonym gap, serving-word noise, retrieval tie-break (Palak), speller 3-letter splits -> brief L1 (wave 5 with A6, B1)
- 2026-10-07T13:24:21Z A5 executor died on API network error (ENOTFOUND) mid-tests; partial diff pipeline +254 tests +160 kept; resumed same agent (round 1, warm context)
- 2026-10-07T13:31:20Z A5 gate PASS (432 passed). DONE_WITH_CONCERNS: lowercase lookalike display names, search alternates confidence 0, _pick_dict lacks rung, resume drops approved, approve saves partial uploads (accepted). Reviewer dispatched; wave5 A6 B1 L1 parallel (disjoint from pipeline.py)
- 2026-10-07T13:33:01Z A5 review CHANGES_REQUIRED (1 important: resume drops approved; 3 minor). Fix round 1 sent to same executor incl. 2 executor concerns (title-case lookalike names, search confidence). Fix gate BASE=9108459 (prompts.py commit in between)
- 2026-10-07T14:17:44Z session restart: resumed A5-fix, A6, B1 (partial work kept); L1 committed 87f709a but gate FAIL test_perf_400k_index 0.053>0.05 under load -> fix round 1 (O(1) tie-break). Eval A5 live: Food_Junction 83 ready+3 review/89, Vithai 53+8/71, Hard_Pending 66+114/226 (+16 needs_price w/ photo)
- 2026-10-07T14:17:44Z Ruling: machine has 7.3 GB RAM (0.4 free with 2 suites) -> parallel full-suite verifies cause MemoryError/timing failures; from now on gates run sequentially on a quiet machine and no parallel executor waves — cost if wrong: slower wall-clock only
- 2026-10-07T14:17:44Z B1 DONE_WITH_CONCERNS: verify failed only on load-sensitive test_sheets tc8 (MemoryError/speed); gemini+config tests pass. Gate later, sequentially
- 2026-10-07T14:31:13Z wave5 merged (A6 B1 L1 gates PASS sequentially), verify-all 456 passed. Vithai A5 audit: 53 ready, 0 wrong (3 text-overlay photos -> judge). dispatch B1 review + B2
