# Autonomous characters and LLM controllers

An LLM controller does not make a character alive by itself. The world must provide motives,
perception, lawful actions, feedback, memory, and ordinary ways to recover from failure. Once
those pieces exist, the model can combine them into choices you did not script.

## Understand the decision loop

On an autonomous turn, Bunnyland:

1. builds a character-scoped prompt from current authoritative projections;
2. adds persona, needs, goals, relationships, obligations, routines, visible events, and
   relevant recalled memories;
3. exposes typed action tools from installed plugins and current context;
4. asks the controller for one native tool call;
5. resolves references and validates the command through normal handlers;
6. returns authoritative results or rejection feedback on the next turn.

The model proposes an action. It does not directly mutate ECS state, declare success, create
relationships through narration, or grant itself knowledge.

## Prepare a character before assigning an LLM

Use this minimum autonomy stack:

| Layer | Question it answers |
|-------|---------------------|
| Identity and persona | Who am I and how do I speak? |
| Current room and reachable entities | What can I perceive and affect? |
| Goal or role | What outcome matters to me? |
| Needs and state | What pressure am I under? |
| Relationships and obligations | Who matters and what have I committed to? |
| Memory profile and seeded context | What relevant past do I carry? |
| Installed actions | What lawful changes can I attempt? |
| Feedback | What actually happened after my attempt? |

If the character cannot answer one of these, improve world state before writing a longer
system prompt.

## Assign control without changing the character

LLM controllers are separate entities carrying provider, model, profile, temperature, token,
style, tool policy, and action cadence configuration. A `ControlledBy` edge assigns one to a
character. Use the inspector or character administration surface to select an existing LLM
controller.

Keep personality on the character, not the model profile. This allows a human to claim Sable
for a scene and release the same Sable back to an LLM without losing biography, inventory,
goals, bonds, or memory.

Use `act_every_ticks` to slow background characters that do not need a decision every dispatch
tick. A market full of model-controlled extras is expensive and narratively noisy. Give major
actors full autonomy; use behavior trees, scripts, suspended controllers, or a slower cadence
for ambient roles.

## Write goals for planning, not puppetry

An LLM goal should describe the desired result and meaningful constraints:

```text
Reopen the ferry safely before moonrise. Preserve emergency supplies and try to repair trust
with Fen rather than taking the oil without agreement.
```

This lets Sable decide whether to inspect the lamp, speak with Fen, consult Lark, retrieve a
wick, or ask Rowan for help. An exact command sequence belongs in a deterministic scripted
controller, not an LLM goal.

Use several autonomous characters only when their goals can interact. If every agent receives
the same mission and facts, they often duplicate work. Give Rowan urgency, Fen stewardship,
Lark truth-seeking, and Sable responsibility.

## Make schedules actionable

Routine and schedule facts can appear in prompt context, but the character still needs a
known route, access, tools, and time. Test the whole chain:

- Does Sable know where the lantern is?
- Is the platform reachable?
- Is inspection an available action?
- Can Sable satisfy hunger before work if necessary?
- Does completing the inspection advance the routine?
- Does missing it leave visible evidence or a recoverable overdue state?

A schedule line without mechanics is a roleplaying suggestion. That can be useful, but label
it honestly in your design.

## Let failures teach the next decision

Rejected commands should identify game-world conditions the character can address. “Matching
key is required” can prompt a search. Internal exceptions, schema failures, and admin
misconfiguration should go to logs and telemetry, not into character prompts; a character
cannot fix the server.

Watch for loops:

- repeating an unavailable action;
- claiming completion in speech before state changes;
- chasing an already resolved goal;
- recalling stale custody as current location;
- oscillating between two needs or routes;
- requesting help repeatedly without anyone accepting.

Correct the world signal, goal lifecycle, action affordance, or rejection feedback rather
than adding a hidden instruction that only one model will follow.

## Tune for ensemble play

Autonomous characters should have enough independence to create scenes without monopolizing
them. Consider:

- different decision cadences;
- private goals and memories;
- shared public evidence;
- asymmetric relationships;
- explicit conversation turns for important exchanges;
- obligations only after real commitment;
- rest or suspension during inactive hours;
- bounded recent-event and recall context.

Humans and models should receive the same authoritative facts even when their clients render
them differently.

## Autonomy review

- Every autonomous character has identity, motive, perception, lawful actions, and feedback.
- Controller configuration is separate from persistent persona.
- Major characters and ambient background roles use appropriate controller cost.
- Goals describe outcomes rather than command scripts.
- Routines connect to reachable places and mechanics.
- Only game-world-resolvable failures reach the character prompt.
- Resolved goals, obligations, and events stop applying pressure.
- Human handoff preserves the same character and world state.

Next, find out whether the living world actually works in
[Playtesting a living narrative](world-building-playtesting.md).
