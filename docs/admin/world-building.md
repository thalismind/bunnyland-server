# World building in Bunnyland

Bunnyland turns familiar setting design into a persistent simulation. A room is not only a
paragraph, a relationship is not only backstory, and a quest is not only something the GM
remembers. They can all become world state that human players and autonomous characters can
observe and change.

This series is for D&D DMs, fiction writers, tabletop designers, interactive-fiction authors,
and other world builders. You do not need to know ECS architecture. Start with the ideas you
already use: premise, place, cast, props, conflict, and consequences.

## The three passes

Build in three deliberate passes. A later pass should deepen a world that already works; it
should not rescue an unclear foundation.

| Pass | What you build | Test question |
|------|----------------|---------------|
| Static | premise, setting, regions, rooms, characters, items, clues | Can a newcomer understand the place by looking around? |
| Interactive | affordances, quests, events, scripts, relationships, obligations | Can players change the world and see authoritative consequences? |
| Living | needs, personal goals, routines, memories, autonomous controllers | Can characters choose meaningful actions when nobody directs them? |

The static pass is like writing a gazetteer or preparing a campaign location. The interactive
pass resembles encounter and adventure design. The living pass gives the cast enough motives,
knowledge, and time pressure to continue acting between authored beats.

## Translate familiar concepts

| World-building idea | Bunnyland form |
|---------------------|-----------------|
| Place or scene | room entity with identity and description |
| Province, district, deck, or dungeon level | region entity containing rooms or smaller regions |
| Route | directed `ExitTo` relationship between rooms |
| Person or creature | character entity plus persona and state components |
| Prop or equipment | item entity contained by a room, character, or container |
| Character motivation | `GoalComponent` on that character |
| Adventure offered to participants | quest entity with objective and reward entities |
| Promise or debt between people | obligation entity linked to debtor and creditor |
| Affection, trust, fear, or resentment | directed `SocialBond` relationship |
| What a character remembers | private memory documents selected through `MemoryProfileComponent` |
| Recurring life pattern | routine, career schedule, needs, and world time |

Components describe what one entity is or its current singleton state. Relationships connect
entities and may repeat. This distinction matters when authoring: one character has one current
goal list, but can have many social bonds; one quest has one current state, but many objective
entities.

## Use one running example

The guides follow **The Lantern Ferry**, a compact scenario suitable for a single session:

- The river has risen and the old ferry lantern has gone dark.
- Bracken Reach contains the village bank and the marsh crossing.
- Ferrymaster Sable wants to reopen the route before moonrise.
- Courier Rowan needs the crossing to deliver medicine.
- The lamp needs a dry wick and lamp oil, but the storekeeper distrusts Sable.
- An old promise explains that distrust, and a ledger records what really happened.

That premise provides a place, a deadline, people with incompatible wants, useful objects, a
route-changing problem, and evidence that can alter relationships. It is small enough to test
but rich enough for multiple solutions.

## Choose an authoring workflow

For a running server, open `world-editor.html` from the web bundle. It can load a live admin
snapshot, expose the installed component and edge catalogue, patch entities, and save the
world. Pause the simulation while making structural edits, especially before changing rooms,
containment, controllers, or quest graphs.

You can also start with a generated draft in `world-generator.html`, then repair it in the
editor. Use generation for breadth and surprise; use deliberate editing for routes, clues,
causality, and completion state. For repeatable behavior, use the script editor or a plugin
rather than relying on an LLM to recreate the same beat.

Before editing a live world:

1. Save or download a snapshot.
2. Confirm the required plugins are enabled.
3. Pause the world if autonomous controllers are active.
4. Make one coherent layer of changes.
5. Validate, inspect, save, and playtest before continuing.

See [Generating worlds](generating-worlds.md) for generator workflows. The rest of this
series assumes you are refining a generated world or authoring one in the world editor.

## Follow the series

### Part I: make a static world

1. [Premise, plot, and setting](world-building-story.md)
2. [Regions, rooms, and routes](world-building-map.md)
3. [Characters and dramatic roles](world-building-characters.md)
4. [Items, clues, and environmental storytelling](world-building-items.md)

### Part II: make it interactive

5. [Affordances, actions, and handlers](world-building-interactions.md)
6. [Quests, goals, and obligations](world-building-quests.md)
7. [Relationships, factions, and social pressure](world-building-relationships.md)
8. [Events, scripts, and consequences](world-building-events.md)

### Part III: make it live

9. [Needs, time, schedules, and routines](world-building-routines.md)
10. [Memories, knowledge, and belief](world-building-memories.md)
11. [Autonomous characters and LLM controllers](world-building-agents.md)
12. [Playtesting a living narrative](world-building-playtesting.md)

### Part IV: expand the world

13. [Expanding an existing world](world-building-expansion.md)
14. [Editing live and saved worlds](world-building-editor.md)
15. [Reading the world graph](world-building-inspector.md)
16. [LLM-assisted world patches](world-building-llm-patches.md)

## A durable design rule

Anything required for progress should be discoverable again. Put route names on signs, task
state in ledgers, object state in descriptions and components, and important knowledge in
repeatable dialogue or memory. A player may reconnect tomorrow. An autonomous character may
enter after the inciting conversation. Neither should depend on an instruction that appeared
once and vanished.

Build truth into the world first. Let prose, clients, prompts, and narration explain that
truth; never make them the only place it exists.
