# Playtesting a living narrative

A living-world playtest is not a reading for prose quality. It is an experiment in whether
people and autonomous characters can perceive, choose, act, recover, and leave a coherent
world behind.

## Start from a known snapshot

Save a baseline before each test run. Record the enabled plugins, world seed, model/provider
profiles, controller assignments, world time scale, and any external scripts. A snapshot lets
you replay the same starting conditions across human, scripted, behavior-tree, and LLM
controllers.

Do not compare two runs that began with different hunger, item custody, open obligations, or
world epochs and call the difference a controller result.

## Test in layers

### Static comprehension

Ask a new participant to identify:

- where they are;
- which routes exist;
- who is present;
- which objects appear important;
- where they could recover required information.

No quest action is needed yet. If the place is confusing while static, autonomy will amplify
the confusion.

### Interactive causality

Exercise every required transition and its failure paths:

- attempt it with the wrong target, missing tool, and unreachable item;
- complete it normally;
- inspect the state from another client;
- try it again to check idempotency;
- save and reload to prove persistence.

Verify actual components, edges, events, and projections rather than trusting narration.

### Living behavior

Run bounded sessions with each autonomous character. Observe whether goals, needs,
relationships, routines, and memory influence different choices. Include interruptions:

- claim a character as a human and release it;
- move an expected item;
- close a route;
- let a deadline pass;
- suspend and resume a character;
- allow one character to give another an unaccepted request.

A good world supports recovery rather than only the happy path.

## Observe through several surfaces

Use the graph inspector to examine map, region, social, and quest structures. Turn on the
event feed to correlate actions with state changes. Use a player client to see only what the
character sees. Use the character-memory admin surface to audit private recall without
exposing it to players.

For LLM diagnosis, traces can show prompt size, recall-filter application, retrieved memory
count, provider attempt, tool call, and validated result. Keep full prompt content capture off
unless a controlled privacy review requires it.

Server logs and telemetry are for internal errors. Character prompts should contain only
conditions they can address in the world.

## Score milestones, not preferred prose

Define authoritative milestones before the run:

| Milestone | Evidence |
|-----------|----------|
| Found the supply conflict | inspected custody and spoke or acted on it |
| Restored the lantern | target state shows repaired and lit |
| Reopened the crossing | route or ferry state changed |
| Delivered medicine | item custody and receipt/delivery event agree |
| Settled the old promise | obligation status and relationship consequence persisted |
| Learned the ledger fact | relevant character memory or repeatable knowledge source exists |

Do not require a specific route unless the test is explicitly about that route. Record which
solution emerged and where the world failed to communicate alternatives.

## Audit world health over time

Persistent simulations reveal problems that short tests miss. Compare snapshots after dozens
or hundreds of ticks:

- total entities and components by type;
- orphan entities with no valid owner or purpose;
- detached or duplicate controllers;
- repeated relationships that violate cardinality;
- unresolved temporary incidents, thoughts, stimuli, or consequences;
- growing supplies, rewards, messages, obligations, or memories;
- stale goals, schedules, and quest tracking;
- CPU, model-call cadence, and prompt size.

Growth is not automatically a leak: memories, history, births, crafted items, and player
writing can be intentional. Every growing class should have a narrative reason, a retention
rule, and a bounded or observable lifecycle.

## Use failures to revise the world

Classify failure before changing anything:

| Failure | Typical revision |
|---------|------------------|
| Did not perceive the destination | add persistent signs, names, or route knowledge |
| Understood but lacked an action | add the correct component, plugin, or handler |
| Acted but state did not change | repair handler or consequence ownership |
| State changed but nobody knew | improve event visibility or persistent evidence |
| Repeated a completed task | resolve or replace stale goals and obligations |
| Chased false memory | expose current state and preserve memory provenance |
| Model alone failed | compare models only after checking world clarity and tool contract |

Avoid solving every failure with stronger prompt instructions. The best fix usually helps
human players, terminal clients, and other models at the same time.

## Release checklist

- A clean baseline snapshot and rollback exist.
- Static navigation works without vanished tutorial messages.
- Required actions pass normal and rejection-path tests.
- Completion is authoritative, persistent, and idempotent.
- Human and autonomous runs can recover from interruption.
- Important memories recall in the intended context and stay private.
- Entity growth and controller counts remain explainable over long runs.
- Internal errors appear in logs, not character-facing context.
- Several valid solutions are accepted when the premise promises them.

With those checks passing, the world is ready to grow. Continue with Part IV,
[Expanding an existing world](world-building-expansion.md).
