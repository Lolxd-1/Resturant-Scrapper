# ORCHESTRATOR STATE
<!-- Source of truth for this run. Any agent or tool resuming work reads this first. -->
run: photo-to-sheet
branch: orch/photo-to-sheet
run-base: 34439a20083ef3a368a36ade389a5f6682c0907a
status: executing
updated: 2026-10-07T13:05:00Z · Claude Code / claude-opus-5-5
<!-- status: recon | planning | awaiting-approval | executing | integrating | done | blocked -->

## NEXT ACTION
A5 gate PASS (432). Reviewer on A5 + wave 5 (A6 B1 L1 worktrees) running. A5 executor concerns -> FIX-A5 brief after review.
Milestone B (Gemini) waits for config/gemini_key.txt from the user; contracts for B go into PLAN before briefing.

## Baseline
tests: 383 passed, 2 skipped (101 s). Pending sheets evidence: shreee 141/228 ready (62%); hotel_shubham 44 pending; food_junction 81/89.

## Tasks
- [x] A1 Matcher rule fixes — w1 — merged 65c2854 (gate PASS)
- [x] A2 Diet + Photo Names columns — w1 — merged 3ef55e5 (gate PASS)
- [x] A3 Swiggy client + merge-insert + image URLs — w1 — merged 882b227 (gate PASS)
- [x] A4 Look-alike names + review status — w2 — deps A2 — 0b4cfca..2d55b00 (gate PASS)
- [~] A5 Pipeline rungs/Swiggy/review — w3 — deps A1 A3 A4 mode=main model=opus base=9404a6f agent=a3964684e99585f4b — gate PASS 9404a6f..e9ef03a — review pending (high risk)
- [~] A6 Review UI + endpoints — w4 — deps A5 mode=worktree
- [~] B1 Gemini client + key setting — w5 — deps A5 mode=worktree
- [~] L1 Lexicon gaps + retrieval tie-break + split rule — w5 — deps A5 mode=worktree
- [ ] B2 Menu photo reader + CLI — w6 — deps B1
- [ ] B3 Pipeline enrich + AI judge — w6 — deps B1 A5
- [ ] B4 Web: key, photo upload, prompt — w7 — deps A6 B1 B2 B3
- [ ] EVAL Eval set + audit — deps A6

## Open questions
- Gemini key: asked user to save it to config/gemini_key.txt (2026-10-07).
