# ORCHESTRATOR STATE
<!-- Source of truth for this run. Any agent or tool resuming work reads this first. -->
run: photo-to-sheet
branch: orch/photo-to-sheet
run-base: 34439a20083ef3a368a36ade389a5f6682c0907a
status: executing
updated: 2026-10-07T13:05:00Z · Claude Code / claude-opus-5-5
<!-- status: recon | planning | awaiting-approval | executing | integrating | done | blocked -->

## NEXT ACTION
Wave 1 merged (421 passed). A4 dispatched in main checkout; then A5 (opus).
Milestone B (Gemini) waits for config/gemini_key.txt from the user; contracts for B go into PLAN before briefing.

## Baseline
tests: 383 passed, 2 skipped (101 s). Pending sheets evidence: shreee 141/228 ready (62%); hotel_shubham 44 pending; food_junction 81/89.

## Tasks
- [x] A1 Matcher rule fixes — w1 — merged 65c2854 (gate PASS)
- [x] A2 Diet + Photo Names columns — w1 — merged 3ef55e5 (gate PASS)
- [x] A3 Swiggy client + merge-insert + image URLs — w1 — merged 882b227 (gate PASS)
- [~] A4 Look-alike names + review status — w2 — deps A2 mode=main
- [ ] A5 Pipeline rungs/Swiggy/review — w3 — deps A1 A3 A4
- [ ] A6 Review UI + endpoints — w4 — deps A5
- [ ] B* Gemini milestone — deps A6 + user key
- [ ] EVAL Eval set + audit — deps A6

## Open questions
- Gemini key: asked user to save it to config/gemini_key.txt (2026-10-07).
