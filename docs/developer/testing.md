# Testing and coverage

Bunnyland uses coverage as a behavioral completeness signal. The goal is not to
make a number look good; the goal is to find typed holes in the behavior model.

An uncovered path means one of two things:

- a reachable behavior is missing a test, including rejection, fallback, malformed
  input, missing data, and runtime error paths; or
- the code is unreachable under valid world and command states, and should be
  removed.

If all reachable behaviors are tested, then all branches should be tested. If all
branches are tested, then any remaining uncovered statement is unreachable. Treat
coverage reports as a map to missing behavior or dead code, not as a reason to add
exclusions.

Use the narrowest layer that proves the behavior. Prefer direct handler tests for
mechanics, table-driven rejection tests, Hypothesis property-based tests for input
spaces and invariants, mocked Discord playtests for player-command loops, and
known-world command sequences that assert the resulting ECS state and events.
Avoid hacky monkeypatch-only coverage that does not correspond to a behavior a
runtime system can exhibit.

Run focused tests with module-form pytest:

```bash
uv run -m pytest tests/test_barbariansim.py
```

Run the default verification gate before handing off a change:

```bash
scripts/test-all
uv run ruff check src tests
git diff --check
```
