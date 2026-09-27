# ORCHESTRATOR STATE
<!-- Source of truth for this run. Any agent or tool resuming work reads this first. -->
run: menu-photo-v2
branch: prodv2.0
run-base: 040e68b3b25564e4dd754713de6810fe6b770bed
status: executing
updated: 2026-09-27T08:10:00Z · Claude Code / claude-opus-5-5
<!-- status: recon | planning | awaiting-approval | executing | integrating | done | blocked -->

## NEXT ACTION
T07 in flight. Then T08, T09, T10, T10B, T11, T12, T13, T15, EVAL (eval menus in scratchpad/eval_menus), FINAL.

## Baseline
Before any change: no tests exist (pytest collects 0 -> exit 4/5); v1 code has no test suite. Every test in this run is new.

## Tasks
- [x] T01 Scaffold, contracts, config, deps, dev venv — o1 — done 5a87e7e..5f6ff1e (gate PASS)
- [x] T04 Zomato client + parsers — o2 — done f3e3014..4c3ac28 (gate PASS; scope hit = orchestrator .gitignore fix)
- [x] T05 Pool store — o3 — done fc7b91f..29a74af (gate PASS)
- [x] T14 Seed pool builder tool — o4 — done b70c54a..7aadf3b (gate PASS)
- [x] DATA1 Seed crawl + commit seed_pool — done 85fc73d (2,311 restaurants, 137,893 items, 20 cities)
- [x] T02 Menu reader — o5 — done 2c0ac0e..1f40f76 (gate PASS)
- [x] T03 Lexicon + text — o6 — done 0e9016a..d9e5c07 (gate PASS)
- [x] T06 Matcher + golden set — o7 — done 4f1bb4f..3b6d625 (gate PASS after round 1; scope hit = DATA1 commit)
- [x] T07 Imaging + vision — o8 — done 69d04b5..9e9ffb7 (gate PASS)
- [x] T08 ImgBB uploader — o9 — done 80915bd..d55a628 (gate PASS + live rotation test)
- [x] T09 Sheets builder — o10 — done a7011b3..ce67e5c (gate PASS, round 1 ruling)
- [x] T10 Pipeline engine — o11 — done d304e0f..b80ac80 (gate PASS; 3 defects -> T10F)
- [~] T10F Fix sheet clear, per-restaurant load, blocked reset — attempt=1
- [ ] T10B Photo swap + CLI — o12 — deps T10
- [ ] T11 Server + app.py — o13 — deps T10B
- [ ] T12 Web UI — o14 — deps T11
- [ ] T13 Launcher + README — o15 — deps T11
- [ ] T15 Eval tool — o16 — deps T10B
- [ ] EVAL Live eval + audit + tuning (orchestrator) — deps T15 DATA1
- [ ] FINAL verify-all, final review, FIX1, push prodv2.0

## Open questions
- none (rulings logged in LEDGER.md)
