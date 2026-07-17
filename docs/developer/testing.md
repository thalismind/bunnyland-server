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

Direct handler calls only validate and return a `MutationPlan`. Tests must execute that
plan explicitly and realize its event factories before asserting committed ECS state or
post-commit events; `HandlerContext` never applies a plan as a side effect.

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

## World-scale performance

`scripts/test-performance` is the routine CI complexity gate. It compares bounded
operations within one run across deterministic worlds through 10,000 entities and edges;
it does not use absolute wall-clock limits tied to one runner. Generated measurements live
under `artifacts/performance/` and are not source artifacts.

Use `scripts/benchmark-world full` for the complete power-of-ten matrix through one
million entities and one million total edges. The runner tests every feasible pair where
the requested unique directed edge count does not exceed
`entities × (entities − 1)`, under balanced and source-concentrated topologies. It records
impossible pairs rather than manufacturing synthetic relationship types or self-loops to
make them appear feasible.

Every entity-count/topology tier runs in a subprocess. A killed or exhausted worker leaves
its earlier JSONL checkpoints intact so memory limits and crashes are results, not missing
data. The full job measures persistence because persistence is intentionally world-scale;
the CI gate omits it because filesystem latency is not a stable per-commit signal.

To inspect one operation with `cProfile`, run:

```bash
scripts/benchmark-world profile \
  --entities 100000 --edges 100000 --topology concentrated \
  --operation mutation_component_high_degree
```

Supported profile operations are listed by an invalid `--operation` value. Profiles and
the raw JSONL/CSV output retain the commit, Python, platform, CPU, timing, and RSS context
needed to compare runs honestly.

## Distribution gate

CI runs packaging only after the test job succeeds. It builds both a wheel and source
distribution, validates them with Twine, installs the wheel with all runtime extras into a
clean virtual environment, discovers plugin entry points, and smoke-tests the `bunnyland`
CLI plus its `tui` and `repl` subcommands. It records `dist/SHA256SUMS` and uploads the exact
artifacts as `python-distributions-${GITHUB_SHA}` for 14 days. Container builds depend on
both the test and package jobs.

External addons should test against that wheel artifact in an isolated environment. Do not
add sibling checkout paths to `sys.path` or `PYTHONPATH`; checking out server source is
acceptable only to build the artifact. PyPI publication remains deliberately disabled until
a signed release/tag policy and Trusted Publisher are configured.
