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

## Development commands

Always invoke pytest through Python's module form. `uv run pytest` can resolve the pytest
console entry point outside the project environment and then fail to import installed
dependencies such as `relics`.

Run a focused file, test, or expression without the full-suite coverage threshold:

```bash
uv run -m pytest tests/test_barbariansim.py
uv run -m pytest tests/test_barbariansim.py::test_specific_behavior
uv run -m pytest tests/test_barbariansim.py -k rejection
```

Add `--all-extras` when the selected tests exercise optional server integrations:

```bash
uv run --all-extras -m pytest tests/test_mcp.py
uv run --all-extras -m pytest tests/test_discord.py
uv run --all-extras -m pytest tests/test_telemetry.py -m otel
```

Do not use `scripts/test-coverage` for an ordinary focused run: the project-wide 100%
threshold correctly fails when only part of the source is exercised. Use it for a complete
serial coverage run when comparing parallel behavior:

```bash
scripts/test-coverage
```

Run the default verification gate before handing off a change:

```bash
scripts/test-all
uv run ruff check src tests
git diff --check
```

`scripts/test-all` is the fast commit and CI gate. It runs the complete required suite
with 100% branch coverage across four worker processes, distributing whole test files so
tests in one module stay together. Set `BUNNYLAND_TEST_WORKERS` to tune the worker count.
The gate writes terminal and XML coverage plus a JUnit report. CI summarizes the XML and
JUnit data directly rather than generating a redundant HTML coverage tree.

Equivalent direct pytest commands are useful when debugging the runners themselves:

```bash
# What scripts/test-all runs, before coverage/report and required-suite checks.
uv run --all-extras -m pytest -n 4 --dist=loadfile

# Tune parallelism without changing the committed default.
BUNNYLAND_TEST_WORKERS=2 scripts/test-all
BUNNYLAND_TEST_WORKERS=8 scripts/test-all
```

For small focused selections, use direct module-form pytest without `-n`: importing the
suite in four workers costs more than it saves. Parallelism is intended for the complete
gate and large test selections.

Use the slower diagnostic modes periodically and when investigating state leakage:

```bash
# Randomized, sequential order; copy the reported seed to reproduce a failure.
scripts/test-ordering
BUNNYLAND_TEST_SEED=123456 scripts/test-ordering

# Run every test in its own forked subprocess.
scripts/test-isolation
```

The ordering mode exposes accidental dependencies on prior tests. The isolation mode
distinguishes those dependencies from failures intrinsic to a test, at the cost of a new
process per test. Ordering retains the same coverage threshold and required E2E/playtest
skip checks as the fast gate. Isolation is deliberately a no-coverage diagnostic because
`pytest-cov` cannot merge execution data from `pytest-forked` children; use the fast gate
for the authoritative coverage result.

Their direct pytest equivalents, without the coverage/report wrapper, are:

```bash
uv run --all-extras -m pytest --random-order --random-order-bucket=global
uv run --all-extras -m pytest --random-order --random-order-seed=123456
uv run --all-extras -m pytest --forked --capture=no
```

The random-order plugin prints the chosen seed at session start. Preserve that seed in a
failure report and reproduce it with `BUNNYLAND_TEST_SEED` or
`--random-order-seed`. Run ordering sequentially: combining global randomization with
xdist makes the execution order scheduler-dependent and therefore harder to reproduce.
The isolation mode disables pytest capture because `pytest-forked` otherwise leaves its
capture handles to finalization in each child, producing plugin-owned `ResourceWarning`s;
test failures still stream directly to the terminal.

## What each gate proves

| Command | Distribution | Coverage | Primary purpose |
| --- | --- | --- | --- |
| `uv run -m pytest PATH` | sequential | no | Fast focused development feedback |
| `scripts/test-all` | four workers, whole files | 100% branch | Commit and CI gate |
| `scripts/test-coverage` | sequential | 100% branch | Compare with parallel failures |
| `scripts/test-ordering` | sequential, globally randomized | 100% branch | Find order-dependent state leakage |
| `scripts/test-isolation` | one subprocess per test | no | Confirm process-state isolation |

The fast and ordering coverage gates reject skipped E2E or Discord playtest cases. Optional
live-service tests remain skipped unless explicitly enabled; those skips do not weaken the
local deterministic gate.

Unexpected warnings fail the test suite. The narrow third-party allowlist covers:

- the exact `discord.py` import warning for Python 3.12's deprecated `audioop`
  standard-library module, imported by `discord.player`; and
- MCP SDK streamable-HTTP cleanup leaving an internal AnyIO
  `MemoryObjectReceiveStream` for finalization after all client-owned streams have been
  explicitly closed.

Project-owned resource, API, collection, and deprecation warnings must be fixed rather than
filtered.

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
acceptable only to build the artifact. Signed version tags publish the previously validated
artifacts through PyPI Trusted Publishing; release jobs do not rebuild them.
