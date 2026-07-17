## What changed

A short description of the change and the request it traces back to.

## Why

The problem this solves, or a link to the issue it closes.

## How it was verified

Spell out how you proved it works — this is the part reviewers lean on, for every
contributor equally.

- [ ] `scripts/test-all` passes (suite + branch coverage, no skipped e2e/playtest)
- [ ] `uv run ruff check src tests` is clean
- [ ] `git diff --check` shows no whitespace errors
- [ ] New handlers / bug fixes include rejection-path tests
- [ ] Visible state changes include prompt-fragment tests
- [ ] No generated artifacts committed (`coverage.xml`, `htmlcov/`, `.coverage`)
- [ ] No compatibility aliases or shims were added

When applicable to the changed surface:

- [ ] REST, WebSocket, and MCP authorization enforce the same scope convention
- [ ] Performance-sensitive paths include representative before/after benchmarks
- [ ] Gameplay mutations do not copy or serialize the full world
- [ ] ECS systems use one indexed driving component rather than A-or-B or full-world queries
- [ ] Async interface changes update every implementation, caller, and test double uniformly

Paste relevant test output, new test names, or trace artifacts:

```
# test output / coverage summary
```

## Notes for reviewers

Anything risky, deferred, or worth a closer look. If a bot or agent authored part
of this, noting it helps with tracing and reproduction — it is a courtesy, not a
disclaimer, and does not change how the PR is reviewed.
