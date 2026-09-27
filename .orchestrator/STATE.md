# ORCHESTRATOR STATE
<!-- Source of truth for this run. Any agent or tool resuming work reads this first. -->
run: menu-photo-v2
branch: prodv2.0
run-base: 040e68b3b25564e4dd754713de6810fe6b770bed
status: executing
updated: 2026-09-27T08:10:00Z · Claude Code / claude-opus-5-5
<!-- status: recon | planning | awaiting-approval | executing | integrating | done | blocked -->

## NEXT ACTION
Dispatch T01 (sonnet). User asked for autonomous completion ("Get it done ... push to github"), so no approval pause.

## Baseline
Before any change: no tests exist (pytest collects 0 -> exit 4/5); v1 code has no test suite. Every test in this run is new.

## Tasks
- [ ] T01 Scaffold, contracts, config, deps, dev venv — o1
- [ ] T04 Zomato client + parsers — o2 — deps T01
- [ ] T05 Pool store — o3 — deps T01 T04
- [ ] T14 Seed pool builder tool — o4 — deps T04 T05
- [ ] DATA1 Seed crawl + commit seed_pool (orchestrator) — bg — deps T14
- [ ] T02 Menu reader — o5 — deps T01
- [ ] T03 Lexicon + text — o6 — deps T01
- [ ] T06 Matcher + golden set — o7 — deps T03 T05
- [ ] T07 Imaging + vision — o8 — deps T03 T04 T05
- [ ] T08 ImgBB uploader — o9 — deps T05
- [ ] T09 Sheets builder — o10 — deps T01
- [ ] T10 Pipeline engine — o11 — deps T02-T09
- [ ] T10B Photo swap + CLI — o12 — deps T10
- [ ] T11 Server + app.py — o13 — deps T10B
- [ ] T12 Web UI — o14 — deps T11
- [ ] T13 Launcher + README — o15 — deps T11
- [ ] T15 Eval tool — o16 — deps T10B
- [ ] EVAL Live eval + audit + tuning (orchestrator) — deps T15 DATA1
- [ ] FINAL verify-all, final review, FIX1, push prodv2.0

## Open questions
- none (rulings logged in LEDGER.md)
