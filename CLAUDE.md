<!-- orchestrate-kit:start -->
## Orchestrated builds
For features, refactors, migrations, or fixes that span several files or steps, use the `orchestrate` skill (`.claude/skills/orchestrate/SKILL.md`).
If `.orchestrator/STATE.md` exists and its `status:` is not `done`, a run is in progress: load that skill and follow its Resume protocol before doing anything else.
Subagents: ignore this section and follow your dispatch.
<!-- orchestrate-kit:end -->
