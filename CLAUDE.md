# Agentic Developer Guide

This guide is for agentic developers working in Bunnyland. It combines general LLM
coding discipline with the project-specific patterns that keep Bunnyland changes small,
testable, and compatible with the existing Relics ECS engine.

## 1. Think Before Coding

**Do not assume. Do not hide confusion. Surface tradeoffs.**

Before implementing:
- State important assumptions explicitly. If an answer cannot be discovered locally and a
  reasonable assumption would be risky, ask.
- If multiple interpretations exist, name them before choosing.
- If a simpler approach solves the request, prefer it and explain the tradeoff.
- If something is unclear enough to affect correctness, stop and clarify.

For multi-step work, use a short goal-driven plan:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

## 2. Keep Changes Surgical

Every changed line should trace to the user request.

- Match existing style, naming, and test layout.
- Do not refactor neighboring code unless the requested change requires it.
- Do not add speculative flexibility, configuration, or abstractions.
- Remove imports, variables, and helpers made unused by your own changes.
- Leave unrelated user or generated work alone. Mention unrelated issues; do not clean
  them up unless asked.

## 3. Relics ECS Modeling

One entity can have only one component of each type.

- Use components for singleton state on an entity.
- Use edges for repeatable relationships or multi-instance state.
- If a character can have multiple instances of something, model it as relationship
  edges with properties, or as separate entities linked by edges.
- Do not add a second component of the same type to represent another instance.

Handler state updates should use the existing ECS helpers:
- Parse ids with `parse_entity_id`.
- Check `world.has_entity(...)` before `ctx.entity(...)` or `world.get_entity(...)` when
  the id came from a command payload or component string.
- Check reachability with `reachable_ids(...)` for player-facing target interactions.
- Update frozen components with `replace_component(entity, replace(component, ...))`.
- Use `spawn_entity(...)` for newly created inventory, quest, event, or resource objects.

## 4. Mechanics And Plugins

Mechanics packs live under `src/bunnyland/mechanics/`; built-in plugin surfaces are wired
in `src/bunnyland/plugins/builtin.py`; player-visible command metadata lives in
`src/bunnyland/core/actions.py`.

Official package-ring terminology:
- **Core verbs** are the shared action surface available across normal worlds.
- **Inner ring** packages are `colonysim`, `gardensim`, and `lifesim`.
- **Outer ring** packages are implemented genre packs outside the inner ring, such as
  `barbariansim`, `daggersim`, `dinosim`, `dragonsim`, `neonsim`, `nukesim`, `toonsim`,
  and `voidsim`.
- **Planned** packages sit outside the metaphorical solar system until implemented.

When adding or changing mechanics:
- Register every public component, handler, event, consequence, and prompt fragment in
  the relevant built-in plugin.
- Add every player-facing command type to `DEFAULT_ACTION_DEFINITIONS`.
- Keep plugin dependencies acyclic. Core/base packs may depend on `core_verbs`,
  `lifesim`, `colonysim`, or `gardensim` only when they actually reuse those mechanics.
- Preserve catalogue numbering and update `bunnyland_mechanics.md` when implementation
  status changes.
- Keep planned or out-of-scope packages/features documented as planned rather than
  quietly implying they exist.

Handler rejection style matters:
- Return `rejected("specific reason")`; tests usually assert exact reason strings.
- Validate invalid ids first, missing entities next, reachability next, then wrong-kind
  and invalid-state checks.
- Cover missing entity guards before dereferencing ids from payloads or component fields.

Prompt fragments should expose newly visible state succinctly and deterministically.
Existing fragments usually collect human-readable lines and return them sorted.

## 5. Documentation Roles

Put documentation where its audience will use it:

- `docs/player/`: player-facing guides, gameplay workflows, and command examples.
- `docs/admin/`: server operation, setup, deployment, moderation, controller handoff.
- `docs/developer/`: engine concepts, architecture, persistence, scripting, worldgen.
- Root docs: project entry points and broad catalogues such as `README.md`, `PLAN.md`,
  `bunnyland_mechanics.md`, and `bunnyland_specification.md`.

When adding or changing player-facing verbs:
- Update the relevant player guide with short command examples.
- Update README status tables when package status changes.
- Update `bunnyland_mechanics.md` if the catalogue is behind the implementation.

## 6. Testing Strategy

Bunnyland uses several test layers. Pick the narrowest layer that proves the behavior,
then add broader tests only when the behavior is actually cross-system.

- **Unit/direct handler tests**: default for mechanics. Use the matching
  `tests/test_*sim.py` file. Follow existing patterns with `build_scenario()`,
  `HandlerContext`, `_handler_cmd(...)`, direct `handler.execute(...)`, exact rejection
  reasons, and direct component/event assertions.
- **Prompt-fragment tests**: add when new state should be visible to agents or players.
  Assert concise text appears in the fragment list.
- **Plugin/catalogue tests**: use `tests/test_plugins.py` for built-in registration,
  dependency hierarchy, action catalogue parity, and dependency-cycle regressions.
- **E2E tests**: use `tests/test_e2e.py` when the behavior requires world generation,
  controller/agent lifecycle, prompt construction, or multiple actor ticks.
- **Discord/playtest tests**: use `tests/test_discord_playtest.py` and
  `examples/playtests/*.json` for larger player-command loops and Discord-facing
  workflows.
- **Live LLM tests**: marked `live_llm`; they are optional and skipped unless explicitly
  enabled with credentials.

For rejection coverage, follow earlier module patterns:
- Prefer table-driven direct handler tests.
- Cover invalid ids, missing entities, unreachable targets, wrong-kind targets, and
  invalid state transitions.
- If enough rejection paths are covered directly, the coverage gate should pass; do not
  run the full gate repeatedly as a progress meter.

## 7. Test Commands

Use module-form pytest:

```bash
uv run -m pytest tests/test_barbariansim.py
uv run -m pytest tests/test_plugins.py
```

Do not use `uv run pytest`; the console entrypoint can miss the `uv` import path and
fail to import dependencies such as `relics`.

Default verification:

```bash
scripts/test-all
uv run ruff check src tests
git diff --check
```

`scripts/test-all` delegates to `scripts/test-coverage`, runs `uv run -m pytest` with
branch coverage, writes coverage artifacts, and enforces the project coverage threshold
from `pyproject.toml` (`fail_under = 97`). It also fails if e2e or Discord playtest tests
are skipped.

Do not run `uv sync` unless the user explicitly asks for dependency syncing.

## 8. Generated And Dirty Files

The worktree may already be dirty.

- Do not revert changes you did not make.
- Do not stage untracked generated work unless it is part of the request.
- Coverage runs may update `coverage.xml`, `htmlcov/`, or `artifacts/coverage/`; check
  `git status --short` before committing.
- Before finalizing code changes, report any untracked or unrelated files left alone.

## 9. Success Criteria

For a completed Bunnyland code change, aim to have:

- Focused tests proving the changed behavior.
- Rejection-path tests for new handlers or bug fixes.
- Prompt-fragment tests when visible state changed.
- Plugin/action catalogue parity when new public surfaces were added.
- Relevant docs updated for player-visible commands or catalogue status.
- `scripts/test-all`, Ruff, and `git diff --check` passing before a final handoff or
  commit, unless you clearly explain why a check could not be run.

These guidelines are working if diffs stay focused, implementation follows existing
mechanics patterns, and test failures point to real behavior rather than avoidable
fixture or command mistakes.
