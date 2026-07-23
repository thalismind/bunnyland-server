# Diegetic guidance and recoverable world design

Bunnyland worlds should teach players through the world itself. Do not rely on one-time
tutorial pop-ups, transient room-entry messages, highlighted traversal paint, or instructions
that disappear after the player touches an item. Human players forget those messages and
LLM-controlled characters reasonably expect places, objects, and evidence to remain available
when they return.

This applies to tutorials and to ordinary generated worlds.

## Design rule

Every fact required for progress should be recoverable from persistent or recurring world
state.

A player who returns after getting lost should be able to rediscover:

- where they are;
- where the relevant destinations are;
- what changed;
- what remains unfinished;
- who can help;
- how to observe or interact with the relevant state.

Use mechanisms people already use to navigate real places:

- named rooms and landmarks;
- signposts and destination signs at decision points;
- maps and directories;
- bulletin boards and posted schedules;
- labels, ledgers, receipts, notices, and incident logs;
- object descriptions and visible state;
- repeatable character dialogue;
- recurring activity and physical evidence left by prior activity.

A highway sign is preferable to a tutorial overlay because it belongs to the place, remains
available, and can be consulted again.

## Avoid the painted-path shortcut

Do not substitute a universal visual marker, glowing outline, or conspicuous "follow this"
paint for coherent world design. These devices can make a route visible without making the
place understandable. They also transfer poorly to text, Discord, assistive clients, and LLM
projections.

Clues should explain themselves in context:

- a sign names the destination and direction;
- a directory shows how facilities connect;
- a worn path, gate, bridge, or stairwell suggests what it reaches;
- a resident describes the route using the same room names the player will encounter;
- an item is stored where its purpose makes sense;
- a ledger or notice reflects authoritative completion state.

Visual presentation may make a real sign readable. It should not replace the sign with an
out-of-world symbol.

## Persistent, recurring, and authoritative feedback

Prefer persistent feedback:

- A notice board can be inspected repeatedly.
- A route map remains in the lobby.
- A parcel locker visibly changes from full to empty.
- A delivery ledger gains a durable entry.
- A broken machine continues to describe its fault until repaired.

Use recurring feedback where persistence would be unnatural:

- A guide repeats directions when asked.
- A bus or courier returns on a schedule.
- Street activity recurs instead of appearing during one narrow tick.
- An NPC can summarize which destinations remain without prescribing an exact action
  sequence.

Feedback about completion must come from authoritative world state. Character notes,
dialogue claims, and controller narration are evidence of belief, not proof that an event
occurred.

## Design for recovery

Put guidance where the player makes the corresponding decision. A central board can explain
the whole area, but junction signs should still identify branches. A multi-room route should
have consistent names in the objective, board, exits, dialogue, and destination room.

When an action is rejected, preserve the exact reason and expose the current alternatives.
Do not silently turn invalid input into a wait or another action. A rejection should help the
player recover without revealing a scripted solution.

NPC help should be repeatable and state-aware. Useful answers include:

- "The Shrine is east through Garden Walk, then south to the footbridge."
- "You have visited the Post Office and Inn; the Shrine is still unchecked."
- "Pip has eaten, but the sealed letter is not within reach."

Avoid dialogue that merely repeats the objective without relating it to visible state.

## Let ordinary play advance the world

Do not require repeated no-op waits as an onboarding puzzle. Waiting several times is not an
interesting human interaction and is rarely an obvious model strategy.

Prefer one of these patterns:

- ordinary movement and interaction advance enough time for activity to occur;
- inspecting a timetable explains when a recurring event will happen;
- arriving at an observation point begins a visible activity cycle;
- speaking to a route checker, worker, or resident exposes the activity through normal play;
- the world leaves persistent evidence if the player misses the live event.

Keep `wait` available for deliberate time passage, but do not make repeated waiting the only
way to discover a tutorial milestone.

## Shared human and agent semantics

Human and LLM controllers should receive the same authoritative facts even when clients
render them differently. If an arrival projection says a resident is in the room, that
resident has been observed; do not require an undisclosed extra `look` ritual only for the
scorer.

World guidance should survive projection into:

- browser prose and visuals;
- Discord messages;
- terminal clients;
- structured LLM prompts and tool results;
- accessibility-oriented clients.

Persistent objects and domain events are the common contract. Client-only pop-ups are not.

## Tutorial difficulty ramp

A tutorial ladder should increase planning and world-model demands, not obscurity.

Use two complementary acceptance measures:

1. **Onboarding floor:** every tested model family, including small models, completes the
   tutorial at least once. This catches undiscoverable or brittle requirements.
2. **Intended-tier reliability:** the target parameter band completes the tutorial
   consistently, with useful milestone progress per turn and few unrecovered rejections.

An initial target may be small 3--4B models for the first tutorial, 7--8B models for the
second, and 20--25B models for the third. Treat those as hypotheses, not reasons to preserve
an unpleasant difficulty spike. If nearly every model misses the same milestone, first
inspect the world's clues, action visibility, and evaluator semantics.

Milestone analysis should report:

- how many models ever reached each milestone;
- how many sessions reached it;
- the smallest parameter band reaching it reliably;
- where characters' notes or dialogue falsely claimed completion;
- whether the blocker was navigation, interaction semantics, timing, tool formatting, or
  missing in-world guidance.

## World review checklist

Before shipping a tutorial or authored world:

- [ ] Every required destination has a persistent, consistently named clue.
- [ ] Every multi-hop route can be reconstructed at its decision points.
- [ ] Required objects remain inspectable until their state meaningfully changes.
- [ ] Important changes leave authoritative, visible evidence.
- [ ] NPC directions are repeatable and use actual room/object names.
- [ ] Players can ask what remains without receiving a scripted solution.
- [ ] Missing a live event does not permanently lose required information.
- [ ] Repeated waiting is optional rather than the core discovery mechanism.
- [ ] Initial and arrival projections count facts they already reveal.
- [ ] Completion comes from authoritative state, not a note or dialogue claim.
- [ ] Human, Discord, terminal, and LLM surfaces preserve the same facts.
- [ ] Playtests include returning to a location after forgetting the original clue.

