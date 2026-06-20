# Contributing to bunnyland-server

Thanks for helping build Bunnyland — an asynchronous social sandbox where humans
and LLM agents share persistent characters in an emergent ECS simulation.
Contributions from people, bots, and human-supervised agents are all welcome.
Whatever wrote the patch, it ships under the same bar: it works, it is tested,
and the diff explains itself.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first. The deeper
engineering conventions live in [`CLAUDE.md`](CLAUDE.md); this document is the
short version.

## Getting set up

This project uses [uv](https://docs.astral.sh/uv/) and targets Python 3.12.

```bash
uv sync --all-extras --dev   # install everything, including optional extras
```

The core engine is the [Relics](https://github.com/ssube/relics) ECS, pinned as a
git dependency. Optional features (Discord, LLM providers, Chroma, OTel, the
FastAPI server, the TUI/REPL clients) live behind extras — see `pyproject.toml`.

## The contribution loop

1. Branch off `main`.
2. Make the smallest change that proves the behavior. Match the existing style,
   naming, and test layout — every changed line should trace to the request.
3. Add or update tests at the **narrowest layer** that proves the behavior (see
   below).
4. Run the full gate locally (lint + tests + coverage).
5. Open a PR using the template. Describe what changed and how you verified it.

## In-tree or external plugin?

Before building a new mechanic, decide where it belongs. Broadly reusable
mechanics that extend the shared world vocabulary land in-tree under
`src/bunnyland/mechanics/`; setting-specific, large, private, provider-specific,
optional-dependency, or experimental work belongs in its **own external plugin
repo** (expose `bunnyland_plugins()`, load with `--module`). The full policy and
an inclusion rubric live in
[`docs/developer/vision.md`](docs/developer/vision.md). If the home is unclear,
open a feature request and say so before coding.

## Testing standards

Testing is not optional here, and it is not an afterthought. The CI gate will
reject anything that does not lint cleanly, pass the suite, and hold the coverage
line. Hold yourself to the same bar before you push.

### Run the gate

```bash
uv run ruff check src tests        # lint (E, F, I, UP, B; line length 100)
scripts/test-all                   # full suite with branch coverage + gates
```

`scripts/test-all` delegates to `scripts/test-coverage`, which runs pytest with
branch coverage, writes artifacts (`htmlcov/`, `coverage.xml`,
`artifacts/coverage/pytest.xml`), and enforces the project thresholds.

Use **module-form** pytest for focused runs:

```bash
uv run -m pytest tests/test_barbariansim.py
```

Do **not** use `uv run pytest` — the console entrypoint can miss the `uv` import
path and silently run against the wrong environment.

### The two hard gates

- **Coverage floor: `fail_under = 97`** (branch coverage). New code needs tests.
  If you are below the line, add focused tests rather than carving exclusions.
- **E2E and Discord playtest tests may not skip.** `scripts/test-coverage`
  parses the JUnit report and fails the build if any `tests.test_e2e` or
  `tests.test_discord_playtest` case is skipped. If those need credentials or
  fixtures to run, fix the fixture — don't skip the test.

### Pick the narrowest test layer

Bunnyland has several test layers. Use the most specific one that proves the
behavior, and only add broader tests when the behavior is genuinely cross-system:

- **Unit / direct handler tests** — the default for mechanics. Use the matching
  `tests/test_*sim.py` file and the existing `build_scenario()` patterns. Prefer
  table-driven tests for rejection paths, and assert the exact `rejected(...)`
  reason strings.
- **Prompt-fragment tests** — add when new state should be visible to agents or
  players.
- **Plugin / catalogue tests** — `tests/test_plugins.py` for built-in
  registration.
- **E2E tests** — `tests/test_e2e.py` when the behavior needs world generation
  or the full server path.
- **Discord / playtest tests** — `tests/test_discord_playtest.py` plus
  `examples/playtests/*.json` for larger player-command loops.
- **Live LLM tests** — marked `live_llm`; optional and skipped unless
  `BUNNYLAND_LIVE_LLM=1` and provider credentials are set. Never make the default
  gate depend on a live model.

### Contract boundaries

The server owns its API contract and ships tests proving responses validate
against the exported contract. Clients own validation of their own server
interaction layer — two-part integration tests live in the client repo under
their own command, not inside the default server gate.

## Before you open the PR

A change is ready for review when:

- [ ] `scripts/test-all` passes (suite + coverage + no skipped e2e/playtest).
- [ ] `uv run ruff check src tests` is clean.
- [ ] `git diff --check` shows no whitespace errors.
- [ ] New handlers / bug fixes include rejection-path tests; visible state
      changes include prompt-fragment tests.
- [ ] Generated artifacts (`coverage.xml`, `htmlcov/`, `.coverage`) are **not**
      committed.

## A note on machine-authored changes

LLM agents and scripts are first-class contributors here — this whole project is
about them — and they are held to exactly the same bar as everyone else, no
higher and no lower. The proof is in the tests and the verification notes, for
human and machine diffs alike. Mentioning that a tool wrote the patch is a
welcome tracing courtesy (it helps with reproduction), not a disclaimer and not a
reason for extra scrutiny. See the [Code of Conduct](CODE_OF_CONDUCT.md) on
machinist non-discrimination.
