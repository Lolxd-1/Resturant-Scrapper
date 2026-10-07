# Planning reference

## Contents
1. Recon
2. PM lens: from request to acceptance criteria
3. Failure pre-mortem
4. Contracts
5. Decomposition and waves
6. Writing briefs an executor cannot misread
7. Test design

## 1. Recon

Goal: a context map precise enough that every brief names exact files, symbols, and commands. Stop recon when you can name every file each task writes and the command that proves it; more reading after that is waste.

Scouts (`orch-scout`, one question each, all in one message). Each prompt is `Question: <question>. OUT=.orchestrator/recon/<topic>.md`. Useful questions:
- "Map the code relevant to <feature>: entry points, request/data flow, module boundaries, key types and functions with file:line."
- "Find existing utilities, patterns and conventions we must reuse for <feature>: validation, errors, logging, config, DB access, HTTP clients, auth checks, test fixtures and factories. Give file:line and how to call each."
- "Map the test setup: frameworks, how to run a single test file, fixtures, mocking conventions, slow or flaky suites, what CI runs."

Restate any CLAUDE.md rule a scout must obey (e.g. "ignore vendor/") in its dispatch; scouts start without it.

Then read yourself: the files you will change, their callers (grep), their tests, and any interface they implement. Record in PLAN under Context map: key files with one-line roles, the data flow in at most 10 lines, and the reuse list. The reuse list is the main defense against duplicated helpers, so make it specific.

## 2. PM lens: from request to acceptance criteria

- Quote the user's request verbatim in PLAN. Restate the goal in one sentence.
- Who uses this and what job it does for them.
- Acceptance criteria AC1..ACn: each observable and testable, including the unhappy paths a user would notice. Good: "POST /v1/orders with an expired token returns 401 and body {\"error\":\"token_expired\"}". Bad: "handles auth errors".
- Non-goals: what we will not build. This stops executors from gold-plating and reviewers from widening scope.
- Assumptions: each with the default you chose. Ask the user only about the ones that change the design.
- Simplicity check: the smallest design that meets every AC. No speculative flags, options, abstractions, or future-proofing. If a simpler approach than the one the user described exists, say so before planning around theirs.

## 3. Failure pre-mortem

Assume the shipped change failed in production. For each lens, write the concrete ways it failed for THIS change. Keep only what applies; don't pad. Each kept item gets a mitigation and a covering test, or a ruling that accepts the risk.

- **Inputs:** empty, null, missing; maximum size; zero, negative, overflow; unicode and encoding; malformed; duplicates; ordering; time zones and DST; locale.
- **State and concurrency:** double submit; races; retries and idempotency; partial failure mid-operation; transaction boundaries; stale caches; event ordering; reentrancy.
- **Dependencies:** timeouts; slow or down services; rate limits; bad responses; bounded retries with backoff; how errors surface to callers.
- **Security:** authentication and authorization on every new entry point; object-level access checks; injection (SQL, shell, template); path traversal; SSRF; secrets in code or logs; PII exposure; CSRF and CORS; rate limiting; new dependency risk.
- **Data:** migration forward and backward compatibility; zero-downtime order; backfills; nullability and defaults; uniqueness and constraints; indexes for new queries; N+1; cascade deletes; retention.
- **Performance:** complexity at realistic sizes; hot-path allocations; blocking I/O in async code; pagination and limits; payload size; memory growth; cold start.
- **Compatibility:** existing callers; public API versioning; error shapes and status codes; serialization; interaction with other features and flags.
- **UI (if any):** loading, empty, and error states; disabled and optimistic states; accessibility; responsive layout; i18n.
- **Operations:** config and env vars with safe defaults; the logs and metrics needed to debug this at 3 a.m.; rollback path.

Output: the PLAN Risks table, `R# | scenario | mitigation | covering test (task)`.

## 4. Contracts

Anything two tasks share is a contract: function and method signatures, types and interfaces, DTO and JSON shapes, tables and columns, event names and payloads, env var names, error codes, module paths, routes.

- Write contracts in PLAN with exact spelling and types. Briefs copy them verbatim; executors never invent shared names.
- If dependents need a contract to exist in code first (types file, migration, interface), make that an early task and commit it before fanning out.
- Changing a contract mid-run is a ruling: update PLAN, update the Notes of every dependent brief, and re-check dependent tasks already marked done.

## 5. Decomposition and waves

Decompose by context, not by role. The executor that writes a behavior also writes its tests; never split "implement" and "test" into separate agents. Role-split agent teams spend more tokens coordinating than working.

A good task: one coherent behavior; 1 to 4 files; its own fast verify command; reviewable on its own; roughly 5 to 30 minutes of human work. Fold scaffolding and config into the task that needs them.

Order: contracts and shared scaffolding, then core logic, then wiring and integration, then API or UI surface, then docs and cleanup.

Waves: a task's deps all sit in earlier waves, and same-wave tasks pass the parallel-safety checks in parallelism.md. Hot files (lockfiles, dependency manifests, migrations, schema, route or DI registries, barrel files, i18n catalogs, global config, CI, generated code) belong to exactly one task per wave, usually an early dedicated task.

Batch repeated small same-shape edits into one task.

Record the DAG in PLAN: `ID | title | deps | wave | write-set | risk | model`.

## 6. Writing briefs an executor cannot misread

The executor is capable but has zero context and follows the brief literally. It sees the brief, the repository, and CLAUDE.md, nothing else.

- Outcome first: what must be true when the task is done.
- Exact everything: paths, symbol names, signatures, messages, numbers, commands, expected outputs. Copy contracts verbatim.
- Name what to reuse: "use `parseMoney()` from src/lib/money.ts:14; do not write a new parser".
- Include code only where precision matters (a tricky algorithm, exact SQL, an exact regex). If the brief contains the complete code, route the task to haiku.
- Test cases as concrete input and expected output, including the edge and error cases from the pre-mortem.
- Verify block: exact commands that exit non-zero on failure, run fast (focused tests plus typecheck or lint of touched files), and never wait for input: no watch modes (`vitest run`, `CI=1 npm test`, `pytest -q`). No servers left running, no fixed ports, no shared databases unless the task owns them. The executor runs this block through `orch.sh verify`, exactly as the gate will.
- Write-set: every path the task may change, one per line with a `create:`, `modify:`, `test:` or `delete:` label. Entries match literally, so `app/[id]/page.tsx` is fine; a trailing `/` allows the whole subtree and `*` is a wildcard (use both sparingly). A rename is two lines (delete old, create new). The gate fails on any other changed file.
- Out of scope: the adjacent things a helpful engineer would be tempted to touch.
- Forbidden phrases: "handle errors appropriately", "add tests", "as needed", "etc.", "similar to T2", TBD. Each one is a guess you are outsourcing to a cheaper model.
- Risk tier: high for authentication or authorization, money, PII or secrets, concurrency, migrations or data deletion, public API; otherwise med or low.
- Size check: a brief longer than about 120 lines means the task is too big. Split it.

## 7. Test design

- Test behavior through public interfaces. Mock only process boundaries: network, clock, randomness, and the filesystem when needed.
- Bug fixes: a test that fails before the fix (RED) and passes after (GREEN), both recorded in the report.
- Every AC gets at least one test; every high risk gets at least one negative test.
- Deterministic: no sleeps (use fakes or events), fixed seeds, fixed clocks.
- Extend existing test files and fixtures before adding new frameworks or helpers.
- Tests that need running services belong in Phase 4 (you run them after merging), not inside parallel tasks.
