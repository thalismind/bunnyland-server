# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"
- When fixing a bug or regression, add a regression test that fails before the fix and passes after it, unless the change is too trivial or impossible to test directly.

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Relics ECS Modeling

**One entity can have only one component of each type.**

- Use components for singleton state on an entity.
- Use edges for repeatable relationships or multi-instance state.
- If a character can have multiple instances of something, model it as an edge with properties, or as separate entities linked by edges.
- Example: multiple jealousies must be represented as relationship edges between the relevant characters with properties like `intensity`, not as one `JealousyComponent` on the character.

## 6. Documentation Roles

**Put new docs under the audience that will use them.**

- `docs/player/` is for player-facing guides and gameplay workflows.
- `docs/admin/` is for server operation, setup, deployment, moderation, and controller handoff.
- `docs/developer/` is for engine concepts, architecture, persistence, scripting, world generation, and design notes.
- Keep root-level docs for project entry points only, such as `README.md`, `PLAN.md`, and broad specifications.

## 7. Test Commands

**Use the README's module-form pytest command.**

- Run the default suite with `scripts/test-all`.
- Run focused tests with `uv run -m pytest ...`, not `uv run pytest ...`.
- The console `pytest` entrypoint can miss the uv import path and fail to import dependencies such as `relics`.
- Do not run `uv sync` unless the user explicitly asks for dependency syncing.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
