# ORCHESTRATOR STATE
<!-- Source of truth for this run. Any agent or tool resuming work reads this first. -->
run: menu-photo-v2
branch: prodv2.0
run-base: 040e68b3b25564e4dd754713de6810fe6b770bed
status: executing
updated: 2026-09-27T08:10:00Z · Claude Code / claude-opus-5-5
<!-- status: recon | planning | awaiting-approval | executing | integrating | done | blocked -->

## NEXT ACTION
TUNE1 in flight, then TUNE2, TUNE3, UIFIX, T13, T15, re-EVAL (6 menus in scratchpad/eval_menus), FINAL review, push prodv2.0. Live eval so far: SBH 16/16 then 18/18 real job; HFC 85/101 all correct; GEV 70/81; GB 92%; LPP 26/35 (chain gaps -> TUNE2); DP crashed (disk full). User TODO(human) open in pipeline._combine_scores.

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
- [x] T10F Fix sheet clear, per-restaurant load, blocked reset — done 0653912..274a102 (gate PASS)
- [x] T10B Photo swap + CLI — o12 — done c7f9f59..7c343f7 (gate PASS)
- [x] T11 Server + app.py — o13 — done 644ba65..378cb7f (gate PASS; test_server slow 111 s -> FIX queue)
- [x] T12 Web UI — o14 — done adb920f..20b7ba9 (gate PASS; committed by orchestrator; UI bugs -> UIFIX)
- [x] TUNE1 Vision veto calibration — done 5cf91c2..9b3acfc (gate PASS; resumed once after maxTurns)
- [x] TUNE2 Chain coverage — done b9752bb..6e90ade (gate PASS; fixed missing diet check in fuzzy chain fallback)
- [x] TUNE3 Brand guard (OCR) — done 8383ae6..b472967 (gate PASS)
- [x] UIFIX — done 2496c43..5e8f08b (gate PASS; 390px verified via iframe since headless min width is 496px; light+dark OK)
- [x] T13 Launcher + README — o15 — done 67fe2cb..ed8b2a9 (gate PASS after Verify-quoting ruling; fresh-PC sim SELF-TEST OK)
- [x] T15 Eval tool — o16 — done 3f43ca5..470b6f8 (gate PASS)
- [x] EVAL — 305/330 (92.4%) coverage, 1 wrong + 2 borderline of 305 (99.7% precision); evidence .orchestrator/reports/eval.md
- [x] FIX1 Swap/rebuild concurrency, honest downloads — done 002d647..d8cd1fc (gate PASS)
- [x] FIX2 Robustness — done 11bdfc0..b45cc29 (gate PASS; resumed twice after maxTurns)
- [~] FIX3 Close gate, logo-check visibility, VC++ runtime, chain rule, swap brand check, pin uv — deps FIX2
- [ ] FINAL verify-all, final review, FIX1, push prodv2.0

## Open questions
- none (rulings logged in LEDGER.md)
