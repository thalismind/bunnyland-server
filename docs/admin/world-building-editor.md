# Editing live and saved worlds

The web world editor works in two modes. Offline, it edits a saved snapshot and downloads the
result. Connected to a server, it applies validated admin patches to the live ECS world. Use
offline editing for large structural revisions and live editing for deliberate, bounded
changes.

## Start safely

Before a live edit:

1. Save and download the current world snapshot.
2. Record the current world epoch and entity count.
3. Pause runtime dispatch for structural work.
4. Confirm the server loaded every plugin used by the saved world.
5. Open `world-editor.html`, authenticate with world administration access, and load the live
   server snapshot.

The editor loads the server's component and edge catalogue, including JSON schemas. This is
the safest source for available types and default fields.

## Understand live and offline differences

| Operation | Offline snapshot | Live server |
|-----------|------------------|-------------|
| Add, edit, or remove component | updates local draft | sends a validated patch |
| Add or remove edge | updates local draft | sends a validated patch |
| Rename entity id | allowed if references are rewritten | not allowed |
| Delete entity | edits draft | deletes entity and removes incoming edges after confirmation |
| Save | download snapshot | call server save after verified changes |
| Undo | reload the original file | restore rollback or apply a deliberate inverse patch |

Live field edits can be sent as you change them. Do not use the live editor as a speculative
scratchpad. Explore risky changes on a downloaded snapshot first.

## Add entities from the outside in

For a new expansion slice, use this order:

1. Create the region or room entities.
2. Add identity, description, and type components.
3. Connect region containment and reciprocal room exits.
4. Add characters, objects, and containers.
5. Add physical containment from exactly one parent.
6. Add social, quest, ownership, controller, and other semantic edges.
7. Add dynamic mechanics such as needs, schedules, hazards, or production.

This order keeps temporary drafts understandable and makes missing structure easier to spot.

## Edit components as singleton state

The component panel shows typed fields when the live catalogue has a schema, plus raw JSON
for inspection. One entity can have only one component of each type.

Use components for identity or current state: one `RoomComponent`, one
`DescriptionComponent`, one `GoalComponent`, one current hunger meter. If a character needs
several debts, objectives, children, owned objects, or memories, use linked entities,
relationships, or the memory store rather than inventing duplicate components.

When changing a frozen component through the editor, the server replaces the component as a
validated unit. Check default fields; deleting an omitted field may reset it rather than
preserve your intended value.

## Edit edges as graph structure

The outgoing-edge panel chooses a registered edge type and target entity. Verify direction:

- room A `ExitTo` room B does not create B to A;
- character `SocialBond` character records the source's feelings;
- quest `QuestHasObjective` objective points from quest to child;
- region or room `Contains` content points from parent to child;
- character `ControlledBy` controller points from persistent actor to replaceable driver.

Setting the same edge type and target updates that relationship's fields. Different targets
are repeatable. Use the inspector after editing to catch accidental inverse direction,
duplicates, missing reciprocal routes, and dangling concepts.

## Delete with narrative and graph awareness

Deleting an entity removes incoming edges too. That prevents dangling ids but can silently
erase important structure: delete a controller and characters lose control; delete an
objective and a quest may become malformed; delete a room and exits and containment disappear.

Before deletion, inspect:

- incoming and outgoing relationships;
- contained entities and their intended new parent;
- controller assignments;
- quest, incident, routine, and script references;
- memories or readable text that name the entity;
- whether historical evidence should remain.

Often the better narrative action is to mark something inactive, destroyed, resolved, moved,
or transformed. Delete ephemeral mistakes and genuine leaked runtime entities; preserve
meaningful history.

## Validate and save

After one coherent edit:

1. Open the graph inspector and review the affected view.
2. Look through the changed entity from both outgoing and incoming context.
3. Resume briefly and confirm systems do not reject or multiply the new state.
4. inspect from a player character's projection.
5. Save the live world explicitly if persistence is configured.
6. Download a post-edit snapshot and run world-health checks.

An accepted patch means its schema and invariants passed. It does not prove the narrative is
discoverable or that your new schedule can be completed.

## Editor review

- A rollback snapshot exists before live mutation.
- Large changes are drafted offline; live patches stay bounded.
- Components represent singleton state and edges represent repeatable links.
- Routes, containment, and social edges point in the intended direction.
- Deleted entities have no required narrative or operational dependents.
- The result is inspected, exercised for several ticks, and saved.
- Entity and controller counts remain explainable.

Next, audit those structures in [Reading the world graph](world-building-inspector.md).
