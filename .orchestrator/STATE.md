# ORCHESTRATOR STATE
<!-- Source of truth for this run. Any agent or tool resuming work reads this first. -->
run: menu-photo-v2
branch: prodv2.0
run-base: 040e68b3b25564e4dd754713de6810fe6b770bed
status: executing
updated: 2026-09-27T08:10:00Z · Claude Code / claude-opus-5-5
<!-- status: recon | planning | awaiting-approval | executing | integrating | done | blocked -->

## NEXT ACTION
T02 in flight; DATA1 crawl running in background (commit data/seed_pool.jsonl.gz when it finishes). Then T03, T06...

## Baseline
Before any change: no tests exist (pytest collects 0 -> exit 4/5); v1 code has no test suite. Every test in this run is new.

## Tasks
- [x] T01 Scaffold, contracts, config, deps, dev venv — o1 — done 5a87e7e..5f6ff1e (gate PASS)
- [x] T04 Zomato client + parsers — o2 — done f3e3014..4c3ac28 (gate PASS; scope hit = orchestrator .gitignore fix)
- [x] T05 Pool store — o3 — done fc7b91f..29a74af (gate PASS)
- [x] T14 Seed pool builder tool — o4 — done b70c54a..7aadf3b (gate PASS)
- [~] DATA1 Seed crawl + commit seed_pool (orchestrator) — bg — running, log %LOCALAPPDATA%MenuStudioseed_crawl.log
- [x] T02 Menu reader — o5 — done 2c0ac0e..1f40f76 (gate PASS)
- [x] T03 Lexicon + text — o6 — done 0e9016a..d9e5c07 (gate PASS)
- [~] T06 Matcher + golden set — o7 — attempt=1
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
