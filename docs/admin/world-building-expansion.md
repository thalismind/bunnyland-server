# Expanding an existing world

A successful living world will outgrow its first map. Players follow an unplanned rumor,
characters form a new household, a faction needs a headquarters, or an unresolved event
deserves a location of its own. Expansion should preserve continuity rather than feeling like
a second unrelated generation pass.

## Expand from pressure already in play

The strongest additions answer an existing question:

- Where does the ferry route go after the far bank?
- Who maintains the river gauges named in Lark's ledger?
- What institution enforces the Ferrymen's Compact?
- Where can Rowan take the medicine next?
- What did the flood expose upstream?

This is the “yes, and” of persistent simulation. New material pays off remembered details,
relationships, routes, and consequences instead of replacing them with a fresh premise.

## Use the expansion loop

1. **Observe:** inspect current topology, active arcs, growth, and character knowledge.
2. **Choose a seam:** select an existing door, route, institution, object, rumor, or person
   that can support the addition.
3. **Snapshot:** save a rollback and pause structural change when appropriate.
4. **Propose:** author manually or ask the world-building LLM for a bounded patch.
5. **Review:** check components, edges, containment, plugins, names, and lifecycle.
6. **Apply:** make one coherent patch and save it.
7. **Integrate:** add clues, memories, goals, schedules, or relationships that connect old and
   new content.
8. **Playtest:** approach from an existing character's limited point of view.

Expansion is complete only when the old world can discover and use the new material.

## Part IV guides

1. [Editing live and saved worlds](world-building-editor.md) covers snapshots, pausing,
   catalogue-driven entity edits, components, edges, deletion, and saving.
2. [Reading the world graph](world-building-inspector.md) uses map, region, social, quest,
   containment, and event views to find narrative and ECS problems.
3. [LLM-assisted world patches](world-building-llm-patches.md) generates bounded room,
   character, item, and event proposals and reviews them before they become canon.

## Preserve continuity at every layer

When adding a new place, connect more than its exit:

| Layer | Continuity question |
|-------|---------------------|
| Geography | Why does this route leave from here? |
| Language | Do old and new signs use the same place names? |
| Custody | Where did new items come from? |
| Social graph | Who already knows or distrusts the newcomers? |
| Goals and quests | Which unfinished arc points here? |
| Memory | Who could remember or recognize it? |
| Schedule | Who visits, works, sleeps, or patrols here? |
| Economy and ecology | What enters, leaves, grows, or is consumed? |
| Operations | What new entities and systems will grow over time? |

Do not retroactively give every character knowledge of the expansion. Add public directions,
personal memories, rumors, or discovery state according to what each character could know.

## Expand in bounded slices

Prefer one complete district with routes, affordances, residents, and reasons to visit over
twenty empty rooms. Keep each patch small enough to inspect and roll back. A useful slice
might be one room, one resident, two items, one relationship to the existing cast, and one
recoverable clue.

After each slice, compare entity counts and active controller load. New content can multiply
simulation work even when the room graph looks small.

Begin with [Editing live and saved worlds](world-building-editor.md).
