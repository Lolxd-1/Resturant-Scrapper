# Failure modes and guards

## Contents
1. Evidence base
2. Multi-agent failure modes (MAST) and their guards
3. Coding-agent failure modes and their guards
4. Recovery playbook
5. Sources

## 1. Evidence base

- **MAST** (Cemri et al., UC Berkeley, NeurIPS 2025): 1,642 annotated traces from 7 multi-agent frameworks, failure rates of 41% to 86.7%, 14 failure modes in three groups: system design 44.2%, inter-agent misalignment 32.3%, task verification 23.5%. The most frequent single modes: step repetition 15.7%, reasoning-action mismatch 13.2%, unaware of termination conditions 12.4%, disobeying the task specification 11.8%. Their interventions: clearer role specs and an added high-level objective check improved success, but no single fix was enough.
- **Anthropic** (multi-agent guidance, 2026): multi-agent setups typically use 3 to 10 times the tokens of one agent; split work by context boundary, not by role; verification subagents tend to declare victory after one or two passing tests unless told to run everything.
- **Cognition** (2025 and 2026): actions carry implicit decisions, so parallel writers conflict; multi-agent systems work when writes stay single-threaded and the extra agents contribute intelligence; a clean-context reviewer finds bugs the author cannot see, averaging about two per PR.
- **Superpowers** (obra): controllers that lost their place after compaction re-dispatched whole completed task sequences; dispatch prompts bloated with pasted history; worker-spawned reviewers duplicated the controller's review; per-finding fix agents cost more than all tasks combined.
- **Claude Code docs and issue reports**: worktree subagents branch from `origin/<default>` unless `worktree.baseRef` is `head`; a subagent's git commands moved the parent checkout's branch; symlinked dependency folders block worktree cleanup; forks copy the parent's context and model; the built-in Explore inherits the session model; a skill's `allowed-tools` grant lasts one turn; after compaction each skill is re-attached up to its first 5,000 tokens.

## 2. Multi-agent failure modes (MAST) and their guards

| Mode | Looks like | Guard in this kit |
|---|---|---|
| 1.1 Disobey task spec | builds something adjacent to the ask | brief is the single spec; Done-when list; gate; reviewer spec check |
| 1.2 Disobey role | executor plans, researches, spawns helpers | executor and scout have no Agent, Skill, or web tools (opencode: denied by permissions); CLAUDE.md pointer tells subagents to ignore it |
| 1.3 Step repetition | finished tasks re-run; same files re-read | write-ahead STATE; `[x]` never redone; resume checks git first |
| 1.4 Loss of history | decisions forgotten after compaction | PLAN, STATE, LEDGER on disk; iron rules at the top of SKILL.md, which is re-attached after compaction |
| 1.5 Unaware of termination | loops forever, or stops early | Done-when per task; Phase 4 definition of done; `maxTurns`; 3-round fix cap |
| 2.1 Conversation reset | a task restarts from scratch | resume dispatch says "finish partial work, do not start over" |
| 2.2 Fail to ask | ambiguous requirement guessed | NEEDS_CONTEXT status; batched questions in Phase 1 |
| 2.3 Task derailment | "improves" adjacent code | Out-of-scope list; surgical rules; gate scope check |
| 2.4 Information withholding | a discovery never reaches later tasks | DISCOVERIES field in every return; orchestrator copies them into briefs |
| 2.5 Ignoring other agents | findings or rulings dropped | fix loop forwards findings verbatim; rulings live in brief Notes |
| 2.6 Reasoning-action mismatch | "tests pass" when they don't | gate re-runs Verify itself; reports are never proof |
| 3.1 Premature termination | "done" with criteria unmet | acceptance walk with evidence for every AC |
| 3.2 No or incomplete verification | only compile or lint checked | task gate, then verify-all against baseline, then final review |
| 3.3 Incorrect verification | tests that cannot fail; wrong command | exact Verify commands in the plan; RED then GREEN for fixes; reviewer checks test quality; slop scan flags skips |

## 3. Coding-agent failure modes and their guards

| Failure | Guard |
|---|---|
| Parallel agents make conflicting implicit choices | contracts and global constraints frozen in PLAN before fan-out; parallel only with disjoint write-sets |
| Stale worktree base causes silent regressions | `worktree.baseRef: "head"`; checkpoint before dispatch; executor checks BASE ancestry |
| Worktree lacks dependencies, tests can't run | `worktree.symlinkDirectories` and `.worktreeinclude` |
| Two agents in one checkout: `index.lock` errors, `git add -A` sweeping others' files | one executor per checkout; explicit `git add <paths>`; no orchestrator git writes while an executor runs |
| A subagent moves the parent's HEAD | executors may not checkout, switch, reset, rebase, or stash |
| Hot-file collisions (lockfiles, migration numbering, registries, barrel files) | each hot file owned by one task per wave |
| Pre-existing failures blamed on new work, or "fixed" out of scope | baseline recorded before any change |
| Tests weakened or skipped to get green | forbidden by executor rules; scope check on test files; slop scan; reviewer |
| Hallucinated APIs or helpers | briefs name exact symbols; executor greps before use, else NEEDS_CONTEXT |
| Duplicate helpers, "v2" functions, needless abstractions | recon reuse list; reuse-before-write rule; reviewer slop rubric |
| Orchestrator context bloat | dispatch by path; returns of at most 10 lines; logs stay on disk |
| Dispatch prompts stuffed with history | 2 to 4 line dispatch; all context lives in the brief |
| Worker-spawned reviewers | no Agent tool for executors (opencode: `subagent` denied) |
| Workers silently run on Opus with the orchestrator's context (fork, general-purpose, built-in Explore) | named agent types only, explicit model, check `/tasks` |
| Executor loosens its own Verify block | gate fails on TAMPER: a non-orchestrator commit touched a brief or PLAN |
| Write-set paths with brackets (`app/[id]/page.tsx`) read as glob patterns | entries match literally first |
| Symlinked `node_modules` in a worktree looks like an uncommitted file | gate ignores untracked symlinks |
| Editable installs or workspace links make worktree tests import the main checkout | parallel-safety check 7 |
| Project hooks block or rewrite bookkeeping commits | checkpoints commit only `.orchestrator/`, with `--no-verify` |
| Permission prompts stall a long run | installer adds an allow rule for `orch.sh`; auto mode covers the rest |
| Test runs leave generated files that fail every gate | `baseline` lists them; ignore them in `.git/info/exclude` |
| One fix agent per finding | one batch-fix executor per review |
| Wrong model silently used | explicit model on every dispatch; check `/tasks` |
| Subagent inherits max effort and overthinks simple work | `effort` set in each agent file |
| Flaky tests | rerun once; if the result flips, log `flaky:` in LEDGER; never mask with skips or sleeps |
| Usage limit hit mid-task | write-ahead STATE; partial subagent output; resume protocol |

## 4. Recovery playbook

- **STATE disagrees with git:** git wins. Rebuild task lines from `git log --grep "chore(orch)"`, find each BASE with `orch.sh base <ID>`, and re-run the gate.
- **Gate FAIL on scope:** decide whether the extra file is genuinely needed. If yes, it's a plan gap: add it to the brief's write-set (log a ruling) and re-gate. If no, have the executor revert that file.
- **Gate FAIL on dirty tree:** the executor didn't commit. Resume it: "commit your write-set files and REPORT".
- **Merge conflict after a parallel wave:** `git merge --abort`; re-run that task sequentially on the new HEAD.
- **verify-all fails although every task passed its gate:** an interaction bug. One executor (sonnet, or opus if subtle) gets the failing output plus the IDs of the tasks involved.
- **Executor keeps hitting maxTurns:** the task is too big or under-specified. Split it, or add the missing context to the brief.
- **An irreversible step looks necessary** (data deletion, force push, schema drop): stop and ask the user.

## 5. Sources

- MAST: https://arxiv.org/abs/2503.13657
- Anthropic, when to use multi-agent systems: https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them
- Cognition, Don't Build Multi-Agents: https://cognition.com/blog/dont-build-multi-agents
- Cognition, Multi-Agents: What's Actually Working: https://cognition.com/blog/multi-agents-working
- Superpowers subagent-driven-development: https://github.com/obra/superpowers
- Karpathy-derived coding guidelines: https://github.com/forrestchang/andrej-karpathy-skills
- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code worktrees (base branch): https://code.claude.com/docs/en/worktrees
- Claude Code skills (lifecycle, compaction, allowed-tools): https://code.claude.com/docs/en/skills
- Stale worktree base reports: https://github.com/anthropics/claude-code/issues/41368 and https://github.com/anthropics/claude-code/issues/57768
- Subagent git commands moving the parent branch: https://github.com/anthropics/claude-code/issues/55708
- symlinkDirectories blocking worktree cleanup: https://github.com/anthropics/claude-code/issues/40259
- opencode V2 agents, tools, skills: https://opencode.ai/v2/docs/agents/ , https://opencode.ai/v2/docs/tools/ , https://opencode.ai/v2/docs/skills/
