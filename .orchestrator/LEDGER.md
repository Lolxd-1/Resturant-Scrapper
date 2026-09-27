# LEDGER (append-only, one line per event)
<!-- format: - <UTC time> <event>. Rulings: "Ruling: <decision> — <why> — <cost if wrong>" -->
- 2026-09-27T16:50:32Z init run=local-menus branch=prodv2.0 base=31bbe1c
- 2026-09-27T16:53:17Z Ruling: autonomous (user asked to fix). Recon: 58/85 distinct misses match once spelled right. dispatch S1 (opus)
- 2026-09-27T17:04:41Z S1 NEEDS_CONTEXT: old test asserted Devanagari reject (now intended to match). Ruling: add test_matcher.py to write-set; keep intent with Tamil + add Devanagari-matches assertion.
- 2026-09-27T17:07:39Z S1 PASS. Audit of 74 real corrections: 3 wrong (kanduri, mith, nag) -> S1B. dispatch S1B (sonnet)
- 2026-09-27T17:12:10Z S1B PASS. dispatch S2 (sonnet)
- 2026-09-27T17:25:03Z S2 PASS. DATA2 crawl started.
- 2026-09-27T17:33:30Z DATA2 first pass only +180 restaurants: localities() read /<city>/restaurants (no locality links; my brief's URL). XS fix f4b20c4 by orchestrator (city home page). Re-running crawl.
- 2026-09-27T17:36:30Z Gavkari with S1/S2 (pool only): 173/215 (80.5%). Audit of all 173: 4 wrong (veg anda kari->egg curry, veg khima->mutton keema, chicken 65->ginger chicken, lachchha->namkeen). dispatch S3 (sonnet).
