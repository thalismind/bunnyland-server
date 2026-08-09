# Needs, time, schedules, and routines

A living world needs reasons to act when no quest marker is flashing. Needs create pressure,
world time creates sequence, and routines make ordinary life recur. Together they let
characters surprise you without becoming random.

## Decide what time means

The world clock records game time, ticks, and time scale. Mechanics use world epoch for
cooldowns, due dates, schedules, weather, needs, and expiration.

Before authoring time pressure, decide:

- how quickly game time should pass during active play;
- whether the world pauses when no players are present;
- which systems advance offline or after reload;
- what counts as morning, a work shift, moonrise, or a season;
- how players can inspect the current time and upcoming events.

Use exact epochs for mechanics and setting language for presentation. “At moonrise” should map
to an observable time or light transition if it can cause failure.

## Add needs that create choices

Needs work best when they compete with other priorities. Rowan's medicine delivery matters,
but hunger and fatigue may make immediate travel risky. Sable wants the ferry reopened, but
sleep and safety still matter.

Common life-sim needs include hunger, thirst, fatigue, hygiene, comfort, fun, social contact,
privacy, and safety. Each meter advances through its own system and is satisfied by matching
world actions and resources.

Use this design test for each need:

| Question | Healthy answer |
|----------|----------------|
| Can the character perceive the need? | prompt and client projections show meaningful bands |
| Can they satisfy it nearby? | food, water, beds, people, shelter, or other affordances exist |
| Does satisfying it cost something? | time, points, money, supplies, travel, or opportunity |
| Can it conflict with another goal? | resting may miss a deadline; helping may delay a meal |
| Is neglect recoverable? | consequences escalate clearly rather than causing unexplained failure |

Do not initialize everyone at crisis level unless the scenario begins as a crisis. A world in
which every autonomous character is starving will be about food no matter what the premise
says.

## Use routines for recurring intentions

`RoutineComponent` records an activity, interval, next due epoch, and last completion. A
routine is a recurring prompt fact, not a teleport or guaranteed action. It tells an
autonomous character that something is due; the controller still chooses among available
verbs and constraints.

Examples:

- Sable: inspect the ferry lantern every morning;
- Fen: count emergency supplies each evening;
- Lark: read the river gauge at noon;
- Rowan: check the courier board after each delivery cycle.

Write activities as outcomes, not path scripts. “Inspect the ferry lantern” permits a
reasonable route and recovery. “Move east, east, use entity_41” is brittle and should be a
deterministic controller script if exact replay is truly required.

## Use specialized schedules when mechanics own them

Some packages provide stateful schedules. Life-sim careers use `JobScheduleComponent` for
next shift, duration, and interval. Environment plugins own day/night, calendar, and weather.
Sim packages may own crops, production, watches, festivals, or travel timing.

Prefer the specialized component when its system changes authoritative state. A biography
line saying “Fen opens the store every morning” will influence roleplay but does not open a
door, start a shift, or enforce business hours.

Connect schedules to places and affordances:

- the worker knows or can discover the destination;
- routes are available when the shift begins;
- tools and work objects are reachable;
- lateness or completion produces visible consequences;
- the schedule recurs after success rather than remaining permanently overdue.

## Layer urgency carefully

Use three time horizons:

- immediate needs, hazards, and conversations compete within the next few actions;
- daily routines and shifts organize ordinary movement;
- quest deadlines, seasons, and faction changes shape longer arcs.

If everything is urgent, autonomous controllers will thrash among warnings. If nothing has a
deadline or recurring pressure, they may exhaust their explicit goals and wait.

Keep the prompt legible by limiting active goals, open obligations, tracked quests, overdue
routines, and critical needs. Archive or resolve stale state instead of letting it accumulate.

## Design for absence and interruption

A character may be claimed by a human, suspended, sleeping, blocked by a locked route, or
offline during the due epoch. Decide whether a routine:

- waits until the character can act;
- expires and records a miss;
- is reassigned to another character;
- leaves physical evidence;
- advances during offline catch-up.

Avoid spawning a new task entity every tick while a routine is overdue. One recurring state
record should remain due until handled, then advance its next due time.

## Routine review

- World time scale matches the intended pace of play.
- Enforced deadlines map to inspectable clock or environment state.
- Every need has reachable and understandable means of satisfaction.
- Initial need levels support the premise rather than drowning it out.
- Routines state outcomes and recur after completion.
- Specialized schedules use their owning plugin mechanics.
- Overdue or blocked schedules cannot leak repeated entities.
- The active prompt contains a manageable number of competing pressures.

Next, give characters continuity across those days in
[Memories, knowledge, and belief](world-building-memories.md).
