# PLAN: <title>
run: <slug> · branch: <branch> · base: <sha> · created: <UTC time>

## Requirement (verbatim)
> <the user's words>

## Goal
<one sentence>

## Non-goals
- <what we will not build>

## Acceptance criteria
- AC1: <observable, testable behavior, including the unhappy path>

## Assumptions
- A1: <assumption> · default: <choice> · asked user: yes/no

## Context map
- `<path>` — <role>
Flow: <request/data flow in at most 10 lines>
Reuse: `<path:line>` — <what it does, how to call it>
Recon notes: .orchestrator/recon/

## Decisions
- D1: <decision> — why: <reason> — rejected: <alternatives and why>

## Global constraints
- Conventions: <naming, error handling, logging, file layout that every task follows>
- Forbidden: new dependencies unless a task lists them; edits outside write-sets; <project-specific>
- Platform and versions: <runtime, framework, DB versions>

## Verify (global)
```bash
# build and typecheck, lint, full test suite: each must exit non-zero on failure
```

## Contracts
```text
# exact shared signatures, types, JSON shapes, tables, routes, env vars, error codes
```

## Risks
| R | Scenario | Mitigation | Covering test (task) |
|---|---|---|---|

## Test matrix
| AC or R | Test (file :: name) | Task |
|---|---|---|

## Task DAG
| ID | Title | Deps | Wave | Write-set | Risk | Model |
|---|---|---|---|---|---|---|

## Rollback
<how to undo safely: revert commits, down-migration, flag off>
