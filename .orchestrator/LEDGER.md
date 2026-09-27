# LEDGER (append-only, one line per event)
<!-- format: - <UTC time> <event>. Rulings: "Ruling: <decision> — <why> — <cost if wrong>" -->
- 2026-09-27T16:50:32Z init run=local-menus branch=prodv2.0 base=31bbe1c
- 2026-09-27T16:53:17Z Ruling: autonomous (user asked to fix). Recon: 58/85 distinct misses match once spelled right. dispatch S1 (opus)
- 2026-09-27T17:04:41Z S1 NEEDS_CONTEXT: old test asserted Devanagari reject (now intended to match). Ruling: add test_matcher.py to write-set; keep intent with Tamil + add Devanagari-matches assertion.
