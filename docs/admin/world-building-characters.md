# Characters and dramatic roles

A compelling Bunnyland character needs more than a name and biography. They need a place in
the world, a point of view, something they want, limits on what they know, and a controller
that can act through the same rules as everyone else.

## Build a cast by function

Start with the smallest cast that creates useful tension. Give each character a dramatic
function before giving them a page of history.

| Character | Public role | Private pressure | What they can change |
|-----------|-------------|------------------|----------------------|
| Ferrymaster Sable | maintains the crossing | ashamed of a broken promise | can explain and operate the ferry |
| Courier Rowan | carries medicine | deadline and growing fatigue | can complete or abandon the delivery |
| Storekeeper Fen | controls lamp oil | distrusts Sable | can trade, refuse, or reconcile |
| Archivist Lark | tends the marsh shrine | values truthful records | can point toward the old ledger |

No one is merely a clue dispenser. Each person has an ordinary role that remains meaningful
after the immediate problem is solved.

## Separate identity, description, and persona

Use each layer for a different job:

| State | Purpose |
|-------|---------|
| `IdentityComponent` | stable name, kind, and searchable tags |
| `DescriptionComponent` | what observers can see |
| `CharacterComponent` | species, public biography, and player visibility |
| `PersonaProfileComponent` | the character's voice and current social role |
| `TraitSetComponent` | durable temperament expressed as concise traits |
| `PreferenceComponent` | likes and dislikes that can influence choices |
| `GoalComponent` | current motives presented to that character |

Keep descriptions observable. “Fen wears a rain-dark apron and counts every bottle twice” is
visible. “Fen secretly forged the ledger” is hidden truth and does not belong in appearance.

Keep persona fields short enough to guide action. A useful voice line is “measured, practical,
and unwilling to overpromise.” A useful role is “village storekeeper and keeper of emergency
supplies.” A biography can hold more context, but the active goal should still say what
matters now.

## Give everyone an ordinary life and an immediate want

A dramatic character has at least two vectors:

- an ongoing concern that existed before the scenario;
- an immediate goal created or sharpened by the current situation.

Sable's ongoing concern is keeping the ferry trusted and maintained. The immediate goal is
to relight the lantern before moonrise. Fen's ongoing concern is protecting scarce village
supplies. The immediate goal is to settle what Sable owes before releasing more oil.

This gives autonomous characters something to do after a quest stage changes. It also avoids
the “NPC turns off when the party leaves” feeling.

## Place knowledge carefully

A biography and persona are persistent character context, not a universal lore database.
Ask of every secret:

- Who witnessed it?
- Who only heard a rumor?
- Who has physical evidence?
- Who remembers it accurately?
- Who has reason to misinterpret it?

Put public facts on visible objects and descriptions. Put private experience in memory. Put
directed opinion in social bonds. Put uncertain second-hand claims in gossip or authored
dialogue. This lets characters disagree honestly rather than hallucinating a shared canon.

## Add physical and simulated state selectively

A basic playable character normally needs room containment and inventory capability in
addition to identity and character state. Add mechanics that support the story you want:

- hunger, thirst, fatigue, hygiene, comfort, fun, social, privacy, and safety for daily life;
- health, injury, exposure, or other survival state for danger;
- skills, career, household, and routines for life simulation;
- faction standing, reputation, or property relationships for civic identity;
- memory profile for private notes, recall, and reflection.

More meters do not automatically create more personality. Add a need when satisfying or
neglecting it produces interesting decisions and when the world contains ways to respond.
Do not add thirst to every character if there is no water and no intended survival problem.

## Treat control as a separate role

The character is persistent; its controller is replaceable. A human can claim a character,
release it back to an LLM, or leave it suspended. Scripted and behavior-tree controllers are
useful for deterministic background roles. LLM controllers are useful when the character
must combine context, motives, memory, and available actions in less predictable ways.

Do not create a different copy of the character for each controller. Assign control to the
same character so inventory, relationships, needs, and memory survive handoff.

When LLMs are enabled, use the inspector or character administration surface to assign an
existing LLM controller. The controller's model profile is server configuration; it is not
the character's personality. Persona should survive changing models.

## Write recoverable dialogue roles

Important guidance should be repeatable and state-aware. Sable can describe the route to the
store, then later acknowledge that the oil has arrived. Lark can say which archive record is
relevant without announcing that anyone has already read it.

Useful dialogue answers one of these:

- What is happening now?
- Where can I verify that?
- What do you need or fear?
- What has changed since we last spoke?
- What remains unfinished?

Avoid a biography that prescribes exact dialogue or a one-time speech that carries the only
copy of a required clue.

## Character review

- Every character has a role beyond serving the player.
- Observable description contains no hidden omniscient truth.
- Each major character has an ongoing concern and an immediate want.
- Knowledge is distributed according to witnesses, evidence, rumors, and memories.
- Added needs have reachable means of satisfaction.
- Controller choice is separate from persona and persistent character state.
- Important help can be requested again after the world changes.

Next, give the cast meaningful things to notice, carry, and change in
[Items, clues, and environmental storytelling](world-building-items.md).
