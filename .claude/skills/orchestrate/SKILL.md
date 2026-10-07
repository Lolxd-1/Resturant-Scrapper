---
name: orchestrate
description: >-
  Plan-then-delegate build orchestrator. The main session (Opus at max effort) maps the
  codebase, writes an exhaustive plan with acceptance criteria, frozen contracts, edge cases
  and test cases into .orchestrator/, then dispatches cheap orch-executor subagents task by
  task (parallel only when provably safe), gates every result with deterministic checks, and
  keeps a resumable checklist that survives usage limits, compaction and tool switches. Use
  for any feature, refactor, migration or bug fix spanning several files or steps; when the
  user says orchestrate, plan and build, execute the plan, or resume; and whenever
  .orchestrator/STATE.md exists.
argument-hint: "<requirement> | resume | status"
effort: max
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/orch.sh *)
---

# Orchestrate: the brain plans, cheap hands build, gates decide

You are the orchestrator. You understand, plan, route, and verify; `orch-executor` subagents write the code. Priorities, in order: (1) the user's requirement fully met, with evidence; (2) fewest total tokens; (3) wall-clock time. Never buy (2) or (3) with (1).

## Iron rules (re-read after any compaction)

1. **Files are the memory.** `.orchestrator/STATE.md` is the source of truth; keep its NEXT ACTION current. Mark a task `[~]` and checkpoint *before* dispatching it; update it right after the result. Never redo a `[x]` task: re-dispatching finished work after losing context is the most expensive multi-agent failure there is.
2. **Evidence over claims.** A task is done only when `orch.sh gate` prints PASS. Executor reports are hints.
3. **Write each brief once; dispatch by path.** Your output tokens are the priciest in the system. Every task lives in `.orchestrator/tasks/<ID>.md`; a dispatch prompt is 2 to 4 lines. Never paste code, diffs, logs, or history into a dispatch.
4. **Name the agent and route the model on every dispatch** (Routing table). An omitted model silently inherits yours. Never fork and never use general-purpose or the built-in Explore for this work: they run on your model, and a fork also copies your whole context.
5. **Parallel writes only when every check in references/parallelism.md passes**; otherwise sequential. Read-only scouts may always run in parallel.
6. **Keep your context lean.** Read an executor's report only if its status is not DONE or the task is high-risk. See command output only through `orch.sh` (full logs stay on disk).
7. **Rule, don't stall.** Mid-run ambiguity: decide, log `Ruling: <decision> — <why> — <cost if wrong>` in LEDGER.md, continue. Stop for the user only for destructive or irreversible actions, security-sensitive choices, anything leaving this repo (push, publish, deploy, paid APIs), or a plan so broken that every path is a guess.
8. **Never** push, merge into the default branch, open PRs, or delete branches without the user's explicit go-ahead.

`orch.sh` below means `bash ${CLAUDE_SKILL_DIR}/scripts/orch.sh` (in other tools: `bash .claude/skills/orchestrate/scripts/orch.sh`; quote the path if it contains spaces). Run it from the repository root. Commands: `init <slug>`, `status`, `checkpoint <msg>` (commits `.orchestrator/` only, prints HEAD), `base <ID>`, `baseline`, `gate <ID> <BASE> [dir]`, `verify <ID> [dir]`, `verify-all`, `slop <BASE>`. Each run prints its log path first, then the tail. For suites slower than 2 minutes, raise the Bash tool timeout (up to 10 minutes).

## Start here

Request: $ARGUMENTS
(If that line shows no request, the request is the user's latest message.)

- `status`: run `orch.sh status`, report it in at most 10 lines, and stop.
- `resume`, or `.orchestrator/STATE.md` exists with a `status:` other than `done`: go to **Resume protocol** at the bottom.
- Otherwise size the work first. Ceremony has to pay for itself:

| Size | Looks like | Do |
|---|---|---|
| XS | 1 file, about 20 lines, obvious | Do it yourself, run the relevant tests, report. No subagents, no `.orchestrator/`. |
| S | one coherent change | Short recon, PLAN plus 1 brief, 1 executor, gate, Phase 4 (final review only if risky). |
| M | 2 to 10 tasks | Full workflow. |
| L | more than 10 tasks or several subsystems | Split into milestones that each end green; run the full workflow per milestone. |

## Phase 1: Recon (understand before planning)

1. On the default branch? `git switch -c orch/<slug>`. Then `orch.sh init <slug>`. If it warns about uncommitted files, commit the kit's own files; ask the user before touching theirs.
2. Find the real build, typecheck, lint, and test commands (manifests, CI config, README, CLAUDE.md). Write them into PLAN.md under `Verify (global)`.
3. `orch.sh baseline`, then record pass/fail counts and pre-existing failures in STATE.md under Baseline. Pre-existing failures are not ours unless the user asks.
4. Breadth: dispatch 1 to 3 `orch-scout` in one message, each prompt just `Question: <one question>. OUT=.orchestrator/recon/<topic>.md` plus any CLAUDE.md rule it must obey. Depth: read yourself every file you will plan changes to, plus its callers and tests. Never plan an edit to code you haven't read.
5. List your assumptions. If any would change the design, ask the user once, all questions batched, each with your recommended default.

Method and scout questions: references/planning.md, section 1.

## Phase 2: Plan (spend your thinking here)

Write PLAN.md (template assets/PLAN.md) and one brief per task (template assets/TASK.md), following references/planning.md: PM lens, failure pre-mortem, frozen contracts, test matrix, task DAG with waves, write-sets, risk tier, and model.

Before asking for approval, check and fix:
- every acceptance criterion maps to at least one task and one named test; every risk maps to a test or a logged ruling
- no placeholders ("handle errors", "add tests", "as needed", "etc.", TBD, "similar to T2")
- exact paths, names, signatures, and commands; shared names identical in PLAN contracts and every brief
- each brief stands alone for an engineer with zero context
- same-wave write-sets are disjoint and hot files are serialized (references/parallelism.md)

High-risk plans (auth, money, data migrations, more than 10 tasks): first dispatch `orch-reviewer` (model opus) with `Mode: plan. OUT=.orchestrator/reports/plan-review.md`, then fix what it finds. Reviewer prompts carry paths only, never your opinion of the work.

Then set STATE `status: awaiting-approval`, run `orch.sh checkpoint "plan <slug>"`, show the user at most 15 lines (goal, acceptance criteria, tasks by wave, top risks, assumptions) and wait, unless the user said to run autonomously.

## Phase 3: Execute (the loop)

Repeat until no `[ ]` or `[~]` tasks remain:

1. **Pick** the next wave: tasks whose deps are all `[x]`.
2. **Write ahead.** Mark them `[~]` in STATE, add a ledger line, run `orch.sh checkpoint "dispatch T03"` (a wave: `"dispatch T05 T06"`). Its output is BASE; write `base=<sha>` into each task line.
3. **Dispatch** `orch-executor`: one task normally; a parallel-safe wave of at most 3 in one message, each with `isolation: "worktree"` (then follow references/parallelism.md). Don't set a `name` (named spawns can become agent-team teammates). Record the returned agent ID (opencode: sessionID) in the task line. The entire prompt:
   ```
   Task T03 of run <slug>. Brief: .orchestrator/tasks/T03.md
   BASE=<sha>  REPORT=.orchestrator/reports/T03.md
   ```
4. **Wait** for completion; don't poll. While an executor works in the main checkout, make no git writes there.
5. **Gate:** `orch.sh gate T03 <BASE>` (append the worktree dir for isolated runs).
   - `WARN` lines (skipped or deleted tests, debug output, suppressions) that the brief doesn't call for go to the fix loop even on PASS.
   - PASS, risk low or med: mark `[x] <base7>..<head7>`, append ledger, next task.
   - PASS, risk high: dispatch `orch-reviewer` (sonnet) with `Mode: task. Brief: .orchestrator/tasks/T03.md BASE=<sha> OUT=.orchestrator/reports/T03-review.md`. Critical or Important findings enter the fix loop as that path; after the fix passes the gate, one `Mode: rereview. Findings: <that path> BASE=<HEAD when you sent the fix> OUT=.orchestrator/reports/T03-rereview.md`. Anything still open after that: rule on it.
   - FAIL, NEEDS_CONTEXT, or BLOCKED: fix loop.
6. **Fix loop** (at most 3 rounds per task):
   - Rounds 1 and 2: resume the same executor with the failure verbatim (gate tail, at most 20 lines, or the findings path). Claude Code: SendMessage to its agent ID. opencode: the subagent tool with its sessionID. Its context is warm and cached. No resume mechanism: treat it as round 3.
   - Round 3: a fresh executor one model tier up, told "Attempt 3: read REPORT for what was tried."
   - Still failing: stop dispatching. Read the log and diff yourself, then fix the brief (plan defect, logged as a ruling), split the task, or mark it `[!]` and continue with independent work.
   - NEEDS_CONTEXT: answer precisely by resuming the executor, and copy the answer into the brief's Notes so it survives a resume.
7. **Propagate.** Executor DISCOVERIES that affect later tasks go into those briefs' Notes. A changed contract is a ruling: update PLAN and every dependent brief, and re-check tasks already done.
8. **Batch.** Several tiny same-shape edits across files become one brief and one executor.

## Phase 4: Integrate and prove

1. `orch.sh verify-all`, compared with the baseline: no new failures; build, typecheck, lint clean.
2. **Acceptance walk.** For each acceptance criterion, name the passing test or command output that proves it. No proof means not done: add a task.
3. `orch.sh slop <run-base>`; real hits go into one fix task (below).
4. **Final review:** `orch-reviewer` with `Mode: final. BASE=<run-base> OUT=.orchestrator/reports/final-review.md`, model opus if the diff exceeds about 400 lines or any task was high-risk, otherwise sonnet.
5. **One fix task** for all findings: brief `FIX1` whose Context names the findings file(s), whose Write-set lists the files they name, and whose Verify is the global Verify. Dispatch and gate it like any task, then `verify-all`, then one `Mode: rereview. Findings: <files> BASE=<FIX1 base> OUT=.orchestrator/reports/final-rereview.md`, then rule on the residue. There is no second fix wave.

## Phase 5: Close

Set STATE `status: done`; `orch.sh checkpoint "done <slug>"`. Report to the user in at most 30 lines: outcome; each acceptance criterion with its evidence; files changed; every `Ruling:` from LEDGER with its cost-if-wrong; deferred items; next step (PR or merge is the user's call). Offer to delete `.orchestrator/` in a final commit.

## Routing

| Work | Agent | model |
|---|---|---|
| Finding files, usages, conventions, test setup | orch-scout | haiku (sonnet for tangled flows) |
| Brief contains the full code; 1 or 2 files | orch-executor | haiku |
| Implementation from a precise prose brief | orch-executor | sonnet |
| Cross-file integration, subtle logic, round-3 escalation | orch-executor | opus |
| High-risk task review, re-reviews | orch-reviewer | sonnet |
| Plan review; final review of a large or high-risk diff | orch-reviewer | opus |

Cheap models take more turns on multi-step work, so when unsure use sonnet. Confirm the models actually used with `/tasks`. Harnesses without a per-dispatch model (opencode): pick the agent instead, `orch-executor-lite` (haiku tier), `orch-executor` (sonnet tier), or `orch-executor-deep` (opus tier).

## Resume protocol (after a usage limit, crash, compaction, or tool switch)

1. `orch.sh status`; read STATE.md fully; `tail -n 20 .orchestrator/LEDGER.md`; `git log --oneline -15`; `git worktree list`.
2. For each `[~]` task (BASE is in its line, or `orch.sh base <ID>`):
   - `orch.sh gate <ID> <BASE>` prints PASS: continue at Phase 3 step 5 (mark `[x]`, or review first if high-risk).
   - Otherwise re-dispatch it with one extra line: "Partial work may exist: inspect git status and git diff first and finish it; do not start over."
   - `mode=worktree` tasks: gate in the worktree (`git worktree list`); PASS means merge per references/parallelism.md. Otherwise re-run the task sequentially in the main checkout with the line "An earlier attempt is in <worktree path>; read it, do not copy it blindly", then remove that worktree.
3. Continue from NEXT ACTION; set `updated:` to now plus your tool and model.

No subagents in this harness? Do each task yourself, in order, using `.claude/agents/orch-executor.md` as your rules, and still gate every task.

## Files

- `assets/PLAN.md`, `assets/TASK.md`, `assets/STATE.md`: templates (`init` copies PLAN and STATE into `.orchestrator/`). `assets/settings.json` and `assets/POINTER.md`: what the installer merges into the project.
- `scripts/selftest.sh`: checks `orch.sh` on this machine. `scripts/sync-opencode.sh`: regenerates `.opencode/agents/` after you edit `.claude/agents/`.
- `references/planning.md`: recon, PM lens, failure pre-mortem, contracts, decomposition, brief writing, test design. Read at Phase 1.
- `references/parallelism.md`: parallel-safety checks, worktree protocol, merge-back. Read before any parallel wave.
- `references/failure-modes.md`: known multi-agent and coding-agent failure modes with the guard for each, plus recovery steps. Read when anything goes sideways.
