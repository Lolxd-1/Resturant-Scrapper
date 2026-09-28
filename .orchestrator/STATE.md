# ORCHESTRATOR STATE
run: local-menus
branch: prodv2.0
run-base: 31bbe1c8b83d807d9a8d5ef00736de9903c58166
status: done
updated: 2026-09-27 · Claude Code / claude-opus-5-5

## NEXT ACTION
S1 in flight (opus). Then S2, DATA2 (Maharashtra-deep crawl), EVAL2 (Gavkari + 6-menu regression + audit), push.

## Baseline
tests: 286 passed. Hotel Gavkari (user's run, latest build): 111/215 ready (52%). Baseline live run here: scratchpad/live_out3/Hotel_Gavkari_before.txt (running).

## Tasks
- [x] S1 Spelling/script normalization — done 10c1c09..1997a2e (gate PASS after 1 ruling)
- [x] S1B Protect local words — done 0bb2c52..738b1c8 (gate PASS; RED->GREEN on all 3)
- [x] S2 Word-driven discovery + locality crawl — done c87a672..6505a8d (gate PASS)
- [x] DATA2 seed +637 MH restaurants (2,954 / 167,574) — committed
- [x] S3 Fix 4 wrong Gavkari picks — done 5b527eb..6925c81 (gate PASS ruled: scope hit = DATA2 seed file)
- [~] EVAL2 Gavkari + 6-menu regression, audit — deps DATA2

## Open questions
- none
