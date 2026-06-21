---
description: Drive modules toward 100% coverage by fanning out review agents over uncovered lines
argument-hint: "[module path, dotted name, or coverage threshold — optional]"
---

# Coverage hunt

Codifies the repeatable process for pushing test coverage toward 100%: find the
weak modules, fan out one review agent per module, and have each agent decide —
per uncovered line/branch — whether it is **unreachable code to remove** or
**reachable behavior to test**, then act. Optional argument `$ARGUMENTS` narrows
the hunt to a specific module/path, or sets a coverage threshold to target.

## The goal is 100% BEHAVIOR coverage

The target is not a line-coverage number — it is **100% behavior coverage**:
every behavior the code can exhibit is exercised by a test, including both the
**happy paths** (valid input, normal flow, success) AND the **unhappy paths**
(invalid/malformed input, rejected commands, error or incompatible
server/LLM responses, missing optional data, empty collections, failure and
fallback branches).

Behavior coverage is the cause; line and branch coverage are the effect. Cover
every behavior and you will naturally fill 100% of branches, and 100% of
branches requires 100% of statements — like filling the back of a shovel fills
the front. So treat an uncovered line/branch as a **missing-behavior signal**:
ask "what behavior is this line for, and which test should exercise it?" If the
answer is "no valid behavior reaches it," that's not a test gap — it's dead code
to remove. Never chase the number with a contrived test that doesn't correspond
to a real behavior, and never paper over a line with a pragma.

## Project conventions (do not deviate)

- Work in the coverage worktree `/home/ssube/tmp/bunnyland-cov-wt/`, branch
  `coverage-bump` (tracks `origin/main`). Do all editing there.
- Shell cwd RESETS between every Bash call — prefix EVERY command with
  `cd /home/ssube/tmp/bunnyland-cov-wt && ...`.
- ALWAYS use `uv run -m pytest` (module form), NEVER `uv run pytest`. Never run
  `uv sync`.
- Per-module coverage, isolated so parallel runs don't clobber each other:
  ```
  cd /home/ssube/tmp/bunnyland-cov-wt && COVERAGE_FILE=/tmp/cov-<tag>.dat \
    uv run -m pytest <test files> --cov=<dotted.module> --cov-report=term-missing -q
  ```
- Full-suite gate: `--cov=bunnyland`; gate is `fail_under = 99.9`, `precision = 2`
  in `pyproject.toml`. Keep it green.
- Lint: `uv run -m ruff check .`. Only judge files YOU changed; pre-existing
  errors in unrelated files (e.g. `scripts/ci_report.py`) are out of scope.
- The pragma budget is **0**. NEVER add `# pragma: no cover`. There is a ratchet
  test (`tests/test_pragma_budget.py`) that enforces this.

## Step 1 — find the weak modules

Run the full suite with coverage and pull out modules below 100% (statement OR
branch). If `$ARGUMENTS` names a module/path, scope to that instead.

```
cd /home/ssube/tmp/bunnyland-cov-wt && COVERAGE_FILE=/tmp/cov-full.dat \
  uv run -m pytest --cov=bunnyland --cov-report=term-missing -q 2>&1 | tail -40
```

Rank candidates by missed statements + partial branches. Prefer batching the
cheap single-branch modules together and giving genuinely large gaps their own
agent.

## Step 2 — fan out one agent per module

Launch the review agents **in parallel** (multiple Agent tool calls in one
message), `subagent_type: general-purpose`, one module each. Each agent owns ONE
source module and ONE test file, picks a single coverage command, and uses it
consistently. Do NOT let agents commit, push, or touch git — they leave changes
in the working tree and report back. Use this prompt template (fill the blanks):

> You are covering the uncovered lines/branches in `<source module>`.
>
> Conventions: work in `/home/ssube/tmp/bunnyland-cov-wt/`; prefix every Bash
> call with `cd /home/ssube/tmp/bunnyland-cov-wt && ...`; use `uv run -m pytest`
> (module form), never `uv run pytest`; never `uv sync`. Coverage:
> `COVERAGE_FILE=/tmp/cov-<tag>.dat uv run -m pytest <test file> --cov=<dotted>
> --cov-report=term-missing -q`. Pick ONE test command + ONE test file and use it
> consistently. Lint with `uv run -m ruff check .` (judge only files you changed).
>
> The goal is 100% BEHAVIOR coverage, not a line number: every behavior — happy
> paths (valid input, success) AND unhappy paths (invalid input, rejections,
> errors, fallbacks) — gets a test. Branch and statement coverage follow from
> that. Treat each uncovered line as a missing-behavior signal: name the behavior
> it's for, then test it (or, if no valid behavior reaches it, remove it).
>
> For EACH uncovered line/partial branch (`NN->MM`), decide which case it is:
>   1. **Reachable behavior → write a real test.** Prefer behavior-driven tests.
>      Reachable cases include: invalid/malformed user input, rejected commands,
>      incompatible or error server/LLM responses, missing optional components or
>      data fields, empty collections, and other realistic edge states. Reasonable
>      monkeypatches are fine (e.g. forcing an optional helper to return None,
>      simulating a missing extra via `monkeypatch.setitem(sys.modules, ...)` +
>      `importlib.reload`, stubbing a server/LLM response).
>   2. **Genuinely unreachable dead code → remove it** with a one-line clarifying
>      comment explaining why the arm can't fire. NEVER add `# pragma: no cover`.
>      Common dead pattern: a parent-detach guard before `world.remove(...)` —
>      Relics cascades inbound `Contains` edges on remove, and `container_of()` /
>      `reachable_ids()` / relationship queries only ever yield live entities, so
>      `has_entity`/`is not None` guards over those are often dead. VERIFY the
>      cascade/invariant empirically before deleting, and confirm the arm is
>      unreachable under any valid, documented circumstance.
>
> Do NOT commit/push or touch git. Edit only your one source module and one test
> file. Report: each branch (line numbers), test-added vs dead-code-removed (+why),
> the test command you used, and final module coverage %.

## Step 3 — verify, commit, push

After agents return:

1. `git status --short` to see the changed files.
2. Full suite + gate: `COVERAGE_FILE=/tmp/cov-full.dat uv run -m pytest
   --cov=bunnyland --cov-report=term-missing -q 2>&1 | tail -25` — must stay green.
3. Confirm pragma budget unchanged: `grep -rn "pragma: no cover" src/ | wc -l`
   (should be 0) and that `tests/test_pragma_budget.py` passes.
4. Lint the changed files only.
5. Commit on `coverage-bump`, then the rebase-merge workflow (remote `main` is
   protected — the push prints "Cannot update this protected ref" but the
   `<old>..<new> main -> main` line confirms it landed; always verify
   `git rev-parse main` == `git rev-parse origin/main`):
   ```
   cd /home/ssube/tmp/bunnyland-cov-wt && git add -A && git commit -m "<msg>"
   cd /home/ssube/tmp/bunnyland-cov-wt && git fetch origin && git rebase origin/main
   cd <base checkout> && git checkout main && git merge --ff-only <sha> && git push origin main
   ```
   Base checkout: `/home/ssube/code/gitea/thalis/bunnyland/bunnyland-server`.

End commit messages with:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
