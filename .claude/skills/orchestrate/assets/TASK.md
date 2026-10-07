# T01: <title>
Wave: 1 · Deps: none · Risk: low · Model: sonnet

## Goal
<what must be true when this task is done, in 1 or 2 sentences>

## Context
<at most 5 lines: why this exists, where it fits, what earlier tasks produced>

## Read first
- `<path>`: <why; symbols to look at>

## Write-set
- create: <path/to/new_file>
- modify: <path/to/existing_file>
- test: <path/to/test_file>

## Contracts
- Consumes: `<exact signature>` (from <task or existing code at path:line>)
- Produces: `<exact signature>`

## Steps
1. <concrete action>

## Test cases
- TC1 (happy): <input> -> <expected output>
- TC2 (edge): <input> -> <expected output>
- TC3 (error): <input> -> <expected error, message, status>

## Verify
```bash
# focused tests for this task, plus typecheck or lint of touched files; must exit non-zero on failure
```

## Done when
- [ ] every test case above passes via Verify
- [ ] <task-specific criterion>

## Out of scope
- <adjacent change the executor must not make>

## Notes
<rulings, answers to executor questions, discoveries from earlier tasks>
