# LEDGER (append-only, one line per event)
<!-- format: - <UTC time> <event>. Rulings: "Ruling: <decision> — <why> — <cost if wrong>" -->
- 2026-10-07T12:25:05Z init run=photo-to-sheet branch=main base=34439a2
- 2026-10-07T12:33:41Z wave1 parallel: write-sets disjoint, no hot files, hermetic pytest, absolute venv path, no editable install -> parallel OK (width 3)
- 2026-10-07T12:33:41Z Ruling: user chose Gemini free tier + manual Gemini-website prompt (Both); look-alikes need approval in a Review list — from AskUserQuestion — cost if wrong: rework of B milestone only
- 2026-10-07T12:34:13Z Ruling: orch-* agent types not loaded in this session (installed mid-session) -> dispatch general-purpose pinned to model sonnet with orch-executor.md as rules — cost if wrong: executor may drift from rules; gate still enforces scope/verify
- 2026-10-07T12:44:31Z wave1 merged: A1 A2 A3 gate PASS, verify-all 421 passed 2 skipped. A3 note: city lat/lng approximations accepted (city centres). dispatch A4
