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
- Prefer one clear null check over repeated `foo?.bar || {}` fallback chains; normalize
  optional data at the boundary, then use the normalized shape internally.

## 3. Relics ECS Modeling

One entity can have only one component of each type.

- Use components for singleton state on an entity.
- Use edges for repeatable relationships or multi-instance state.
- If a character can have multiple instances of something, model it as relationship
  edges with properties, or as separate entities linked by edges.
- Do not add a second component of the same type to represent another instance.
- Use `GraphQuerySpec` only for bounded, connected conjunctive joins over plugin-registered
  types. Do not add raw graph-query access to player or agent surfaces; register a typed,
  claim-scoped perspective question instead.
- For live entity references, document why a component field is singleton state; otherwise
  prefer a directed edge with explicit cardinality, cleanup, visibility, and migration rules.

Handler state updates should use the existing ECS helpers:
- Parse ids with `parse_entity_id`.
- Check `world.has_entity(...)` before `ctx.entity(...)` or `world.get_entity(...)` when
  the id came from a command payload or component string.
- Check reachability with `reachable_ids(...)` for player-facing target interactions.
- Update frozen components with `replace_component(entity, replace(component, ...))`.
- Use `spawn_entity(...)` for newly created inventory, quest, event, or resource objects.

System-to-component mapping must preserve indexed candidate selection:

- Give each independent system effect one driving component: the component whose state the
  system owns or changes. Select it with `with_all([DrivingComponent])` so Relics starts
  from that component's index.
- Do not use `with_any([A, B])` for systems, and do not query the whole world before
  branching on `has_component(A)` or `has_component(B)`. Split independent A-or-B behavior
  into separate systems.
- An entity with both components should run once in each independent system. An entity with
  only one should run only in that component's system.
- Keep a single A-and-B system only when one semantic effect inherently requires both
  components. Express that contract as `with_all([A, B])`; do not query A and discover B in
  the processing loop.
- `with_none(...)`, secondary indexes, and bounded relationship conditions may refine an
  indexed driving set. They must not turn a bounded system into a full-world scan.
- Cover A-only, B-only, both, and neither in behavior tests. When query shape changes, add
  or update a performance test proving cost scales with matching candidates rather than
  total world size.

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
- Root docs: project entry points and broad catalogues such as `README.md`,
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

Client/server API contracts should be explicit and shared:
- The server owns authoritative DTOs, OpenAPI/JSON Schema, and server-side contract
  tests that prove responses validate against the exported contract.
- Clients own validation of their server interaction layer. Two-part integration tests
  that start or target a real server and exercise a client adapter should normally live
  in the client repo, in their own run such as `test:contract` or
  `test:server-integration`, not inside the default server gate.
- Keep the default server gate focused on authoritative behavior, projection filtering,
  schema stability, and backward-compatible response shapes.
- Use named typed request and response models for API contracts. Avoid returning or
  accepting ad hoc dicts for client-facing endpoints once a surface is part of the
  contract; stable model names make OpenAPI/schema checks and client validation reliable.
- Prefer projection routes shaped as `/world/{projection}/{id}`. The client is implied;
  the projection type scopes how to interpret `id`. Examples: `/world/character/123`
  for a character-scoped play view, `/world/room/123` for a room-scoped view, and
  `/world/dm/123` for a DM/moderator-scoped projection.
- Enforce privileged projections such as DM/moderator views with explicit server-side
  permission checks. Do not make a projection admin-only by moving it under an
  `/admin/...` path; keep the projection route stable and guard access before producing
  the DTO.
- Projection DTOs are client-facing contracts. Do not expose raw ECS entities, component
  maps, relationship maps, private memory, hidden state, raw controller context, or
  implementation-only metadata through them.

For rejection coverage, follow earlier module patterns:
- Prefer table-driven direct handler tests.
- Cover invalid ids, missing entities, unreachable targets, wrong-kind targets, and
  invalid state transitions.
- If enough rejection paths are covered directly, the coverage gate should pass; do not
  run the full gate repeatedly as a progress meter.

Coverage is a behavioral completeness signal, not a scoreboard. Bunnyland treats
untested paths like typed holes: every reachable behavior, including runtime error and
rejection paths, needs a real behavior test; any statement left uncovered after all
behaviors are tested is presumed unreachable and should be removed. Prefer comprehensive
input tests, Hypothesis property-based tests, direct handler tests, mocked Discord
playtests, and known-world command sequences over hacky monkeypatch-only coverage. Use
coverage reports to find missing behavior or dead code, not to justify exclusions. See
`docs/developer/testing.md` for the project testing philosophy.

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
from `pyproject.toml` (`fail_under = 100`). It also fails if e2e or Discord playtest tests
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

## 10. Async Contracts Are Uniform

An async interface must be async in every implementation and at every call site.

- Do not return `T | Awaitable[T]` or use runtime awaitability inspection.
- Do not add execution-mode flags or adapter branches to preserve synchronous
  implementations. Migrate implementations and callers to the async contract.
- Keep scheduling policy in the caller and apply it uniformly.
- Open telemetry spans before invoking async methods and await those methods inside the
  span. Background runners receive the agent and arguments, not a pre-created coroutine.
- Update implementations, direct callers, test doubles, and tests together when migrating
  an interface.

These guidelines are working if diffs stay focused, implementation follows existing
mechanics patterns, and test failures point to real behavior rather than avoidable
fixture or command mistakes.
