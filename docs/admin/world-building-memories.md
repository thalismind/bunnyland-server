# Memories, knowledge, and belief

Memory is how a living character carries the past into a new room. It should preserve what
that character experienced or was told, including uncertainty, without replacing
authoritative world state.

## Distinguish four kinds of knowledge

| Kind | Best home | Example |
|------|-----------|---------|
| Public persistent fact | readable object, description, component, or relationship | the ferry notice says the crossing is closed |
| Stable personal context | biography, persona, trait, or preference | Sable has maintained the ferry for twenty years |
| Private episodic memory | memory document | Sable remembers arguing with Fen during the last flood |
| Current authoritative state | ECS component or edge | the oil flask is now in Rowan's inventory |

Memory can say “I left the oil in the store.” If someone moved it later, that memory remains a
valid recollection but an invalid inventory fact. Controllers should combine recalled context
with current projections rather than treating memory as omniscient truth.

## Give each character a memory profile

`MemoryProfileComponent` names a private vector collection and optional shared collections.
Private notes, remembered events, and reflections live in the memory store rather than as ECS
entities. This keeps unbounded text outside the world graph and protects it from ordinary
player projections.

Use one stable collection per character. Do not point unrelated characters at the same
private collection merely to make lore convenient. Use shared collections only for knowledge
that genuinely belongs to a household, institution, archive, or other shared context and when
the server's access design supports it.

The web `character-memory.html` admin page can inspect memory-enabled characters and edit
documents and metadata. Treat it as private operator access.

## Seed only actionable memories

A new character benefits from a few memories that explain current relationships, routes,
custody, and unresolved motives. For Sable:

- “Fen delivered emergency oil during the last flood, but one sealed bottle later vanished.”
- “The Marsh Shrine ledger records every transfer made by the Ferrymen's Compact.”
- “The lantern platform is east of the landing and requires a dry wick before it can be lit.”

These memories can influence choices. A generic childhood vignette may enrich prose, but it
should not crowd out facts needed for present action.

Include provenance in text or metadata when it matters: witnessed, told by Fen, read in the
ledger, inferred, or uncertain. Memory search can rank relevance, but relevance does not
establish truth.

## Design automatic recall

When a memory store is attached, character prompts can include a bounded `Recall` section.
The recall filter builds a query from current location, visible people and items, and recent
room context, then selects a few relevant private memories. Irrelevant documents remain
available through explicit remember actions without filling every prompt.

For reliable recall:

- use the same stable names for rooms, people, and items that current projections use;
- keep one memory focused on one useful episode or fact cluster;
- avoid giant lore dumps with many unrelated names;
- preserve source and time metadata;
- test recall in the room where the memory should matter;
- confirm private content is never included in another character's projection.

Automatic recall is contextual, not guaranteed for every stored document. If a fact is
required for all participants to finish a quest, put a recoverable copy in the world.

## Let characters create memories through play

Characters can take private notes, remember, reflect, and forget when the memory plugin is
enabled. Background reflection can synthesize a bounded higher-level memory after enough new
entries accumulate.

Encourage memories of:

- promises made and whether they were kept;
- where an important object was last seen;
- route discoveries and hazards;
- social interpretations and their source;
- quest outcomes and unfinished threads;
- changes that should affect future plans.

Do not save every event forever. Repetition makes retrieval noisy and storage grow without
adding continuity. Prefer significant transitions, compact summaries, and deliberate
forgetting or retention policy.

## Use memory to support disagreement

Seed different perspectives rather than one copied lore packet. Fen remembers releasing the
oil. Sable remembers finding the store empty. Lark remembers a torn ledger page. Those
memories produce an investigation because no individual begins with complete truth.

When evidence appears, a character can write a new memory or reflection. Do not silently
rewrite the old memory; remembering that one was mistaken is narratively richer than having
always known the answer.

## Memory review

- Required public facts have persistent world sources outside private memory.
- Each character's seeded memories match what they could know.
- Collection ownership and sharing respect privacy boundaries.
- Entries use stable world names and useful provenance.
- Automatic recall is tested in relevant context.
- Current ECS state remains authoritative when memory is stale.
- Reflection summarizes rather than multiplying near-duplicates.
- Retention prevents unbounded memory growth.

Next, let characters use goals, needs, routines, and recall in
[Autonomous characters and LLM controllers](world-building-agents.md).
