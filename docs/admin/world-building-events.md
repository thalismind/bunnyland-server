# Events, scripts, and consequences

Events say what happened. Scripts arrange deterministic beats. Consequences translate one
authoritative occurrence into another state change. Use them to make a world responsive
without turning it into a brittle cut-scene sequence.

## Distinguish the tools

| Tool | Purpose | Example |
|------|---------|---------|
| Typed domain event | factual record emitted by a handled change | the lantern was repaired |
| External script | deterministic trigger plus commands or narrow admin patches | ring the warning bell at moonrise |
| Consequence/reactor | reusable rule responding to an event | a fulfilled promise improves trust |
| Storyteller incident | budgeted pressure with spawned requirements and resolution | a flood surge damages the landing |
| Controller script | fixed sequence of character tool calls | a sentry patrols north and south |

These are not interchangeable. A domain event is evidence, not a command to the LLM. An
external script lives beside ECS state and does not own durable truth. A controller script
acts as one character through ordinary validation.

## Use events as the causal seam

A handler should emit a typed event only after planning a valid mutation. Other systems can
then react without parsing prose.

For Lantern Ferry:

```text
LampRepairedEvent
→ objective completion consequence checks actual lamp state
→ FerryReopenedEvent changes route or notice state
→ observers receive visible facts
→ relevant characters may store memories
```

Avoid a consequence that trusts the event name alone when current state matters. If a repair
event names the wrong target or the required delivery has since been reversed, validation
should prevent a false completion.

## Author external scripts for reliable beats

The script editor creates JSON definitions containing named blocks. A block has a trigger,
actions, priority, execution policy, and optional cooldown.

Supported triggers can match:

- every tick;
- a minimum world epoch;
- a domain event type;
- exact event field values;
- combinations using all, any, and not.

Actions can submit a normal command for selected characters or apply narrow world patches.
Commands run through normal handlers on a later tick. Patches apply directly after the tick
and should be reserved for setup or state that has no character action.

A moonrise warning could be a once-only epoch trigger that submits a `say` command to a
reachable herald. A recurring ferry bell could use `always` with a game-time cooldown. Never
use `always` without considering how many entities or messages it can create.

## Keep scripts recoverable and idempotent

Script block identity and fired state are persisted separately from ECS state. Use stable
script ids and block names. A once-only block should be safe if an operator reloads its
definition or restores an older snapshot.

For every block, ask:

- What prevents it from firing twice?
- What happens if its target moved or was deleted?
- Does a failed action leave the block eligible for retry?
- Does the script spawn permanent entities?
- Can a cooldown bound repeated work?
- What visible evidence remains if nobody observed the live event?

Prefer updating a notice, component, or existing incident over spawning another copy each
tick.

## Use storyteller incidents for pressure, not plot control

The storyteller accumulates an incident budget and selects eligible plugin-contributed
incidents. An active incident is an entity with `IncidentComponent`; spawned requirements are
linked by `IncidentSpawned`. Resolution rules inspect world state to decide when the incident
is finished.

Incidents work well for storms, supply drops, hostile arrivals, damage, and other pressures
that can enter an established simulation. They should create a problem or opportunity, not
force a particular character decision.

Give every incident:

- a bounded cost and spawn count;
- a sensible location;
- visible and persistent signs;
- at least one resolution rule grounded in world state;
- cleanup or transformed aftermath;
- no dependency on one fleeting prompt line.

## Design consequences in both directions

The immediate “success” is rarely the whole story. Map downstream effects:

| Event | Mechanical consequence | Narrative consequence |
|-------|------------------------|-----------------------|
| oil transferred | inventory changes | Fen has taken a risk |
| lantern repaired | lamp and route state change | village can cross after dark |
| promise fulfilled | obligation closes; trust rises | old grievance can soften |
| medicine delivered | recipient and quest state change | Rowan's next goal becomes possible |

Do not let two consequences own the same state transition independently. Choose one
authoritative owner and let other systems observe its event.

## Event review

- Important state transitions emit typed, visibility-scoped events.
- Scripts trigger on structured events or world time, never parsed narration.
- Character actions are submitted as commands rather than applied as admin patches.
- Always-running blocks have cooldowns and bounded output.
- Incident resolution checks authoritative world state.
- Every transient beat leaves persistent or repeatable evidence when needed.
- Spawned entities are consumed, cleaned up, or transformed after resolution.
- One mechanic clearly owns each state transition.

The interactive layer is complete. Next, let time matter in
[Needs, time, schedules, and routines](world-building-routines.md).
