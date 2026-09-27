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
