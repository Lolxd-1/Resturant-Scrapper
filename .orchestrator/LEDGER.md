# LEDGER (append-only, one line per event)
<!-- format: - <UTC time> <event>. Rulings: "Ruling: <decision> — <why> — <cost if wrong>" -->
- 2026-09-27T06:49:44Z init run=menu-photo-v2 branch=prodv2.0 base=040e68b
- 2026-09-27T08:10Z Ruling: run autonomously without the approval pause — user said "Get it done ... push this to the github. that's it." — cost if wrong: user sees the plan only at the end.
- 2026-09-27T08:10Z Ruling: sequential execution only (no worktree waves) — Windows symlinked .venv unreliable; shared hot files — cost if wrong: longer wall clock.
- 2026-09-27T08:10Z Ruling: drop freeimage.host fallback — public key returns "Internal upload error" (code 111) for multipart, base64 and URL uploads — cost if wrong: one fewer fallback host; multi-key ImgBB rotation covers the ask.
- 2026-09-27T08:10Z Ruling: vision = CLIP ViT-B/32 as verifier only (measured fine top1 0.27, coarse 0.72) — cost if wrong: re-tune weights in EVAL.
- 2026-09-27T08:10Z Ruling: push to new branch prodv2.0 (repo convention prodv1.0); PR/merge to main left to user.
- 2026-09-27T08:10Z Ruling: Streamlit removed; FastAPI + vanilla SPA — needed for Apple-grade UI and background jobs — cost if wrong: no hosted Streamlit URL (user said local PC use).
- 2026-09-27T07:38:42Z dispatch T01 (sonnet)
- 2026-09-27T07:38:56Z Ruling: orch-executor/orch-reviewer not registered in this session (kit installed mid-session) — dispatch general-purpose with an explicit model and the instruction to follow .claude/agents/orch-executor.md (or orch-reviewer.md) verbatim — cost if wrong: executor has extra tools; the gate still enforces scope.
- 2026-09-27T07:44:26Z T01 gate PASS 5a87e7e..5f6ff1e. Vision bench: nomic-Q fine top1 0.23 (worse), jina-clip failed to load under cp1252 locale (tokenizer json read) -> keep CLIP; PYTHONUTF8=1 required in launcher. User supplied an ImgBB key mid-run; stored in git-ignored config/settings.json as 'Team key 1'.
- 2026-09-27T07:44:44Z dispatch T04 (sonnet)
- 2026-09-27T07:59:32Z Ruling: removed '!tests/fixtures/**' from .gitignore (my T01 brief defect: un-ignored __pycache__) — fixtures are generated in code — cost if wrong: none. T04 TC12 threshold 180->140 accepted (144 real restaurants with photos; 20,459 items matches recon).
- 2026-09-27T07:59:56Z T04 PASS (ruled). dispatch T05 (sonnet)
