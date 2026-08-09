# LLM-assisted world patches

Bunnyland can ask its world-building model to propose a room, character, item, or event for an
existing world. The model receives bounded structured context and returns validated proposal
data. Server code compiles that proposal into ordinary world-patch operations.

The model never receives direct access to the ECS. Treat its output like a junior co-designer's
draft: useful, surprising, and always subject to review.

## Choose the smallest generation target

| Target | Required anchor | Good use |
|--------|-----------------|----------|
| Room | an existing door contained by a room, plus direction | continue one established route |
| Character | an existing room | add a resident who belongs in that scene |
| Item | a room, character, or container | add a prop with correct initial custody |
| Event | an existing room | introduce a bounded local development |

Do not regenerate the whole world to add one shopkeeper. Bounded generation preserves entity
ids, history, memories, relationships, and player changes outside the patch.

## Generate through the graph inspector

When connected to a server configured for LLM world building:

1. Save a rollback snapshot and pause if the expansion is structural.
2. Select the anchor room, door, character, or container.
3. Use **Add Room**, **Add Character**, **Add Item**, or the relevant entity action.
4. Enter a concise prompt describing narrative job, constraints, and continuity.
5. Wait for the generation job to return a patch and for the inspector to apply it.
6. Inspect every created entity and edge before resuming normal play.

The inspector's convenient flow generates and applies the returned patch. Use it only when
you are comfortable reviewing after application and restoring the snapshot if necessary.

Admin MCP tools such as `admin_generate_room`, `admin_generate_character`,
`admin_generate_item`, and `admin_generate_event` return the proposed patch separately. An
operator or coding agent can review those operations, revise the proposal outside the server,
then call `admin_patch_world` with the accepted operations. Both generation and application
require world administration scope.

## Write prompts as design briefs

A useful patch prompt names:

- the addition's narrative job;
- facts it must preserve;
- entities or place names it should connect to;
- tone and sensory contrast;
- required affordances or clues;
- what it must not resolve or reveal;
- a strict size boundary.

Example room brief:

```text
Add one cramped river-gauge hut east of this floodgate. It belongs to Bracken Reach and uses
the same practical folk-horror tone. Include a persistent gauge log showing that the water
rose before the lantern failed. Do not reveal who removed the oil, add another route, or
create more than two portable objects.
```

Example character brief:

```text
Add one retired gauge keeper who lives in this hut. Give them an ordinary maintenance role,
a cautious voice, and partial knowledge of the flood timeline. They should recognize Lark but
not know Rowan or the current medicine quest. Make them suspended for later controller
assignment unless a reusable LLM controller is explicitly available.
```

Avoid asking for component names in free-form prose unless you are reviewing a technical
patch. Describe capabilities and let the registered generation schema and plugin enrichers
choose supported state.

## Review the patch as graph surgery

Before accepting or keeping a generated patch, inspect:

| Area | Review |
|------|--------|
| Scope | Only expected entities and existing anchors changed. |
| Identity | Names are stable, distinct, and consistent with old clues. |
| Components | Types are registered; fields are plausible; singleton state is not duplicated. |
| Containment | Every physical addition has exactly one correct parent and mode. |
| Routes | New room exits are intentional and reciprocal where appropriate. |
| Controllers | Generated character control is valid; redundant reusable controller profiles are not left behind. |
| Knowledge | New biography and memory do not grant omniscient facts. |
| Mechanics | Claimed actions have actual components and enabled plugins. |
| Lifecycle | Supplies, incidents, rewards, and temporary entities can resolve or be consumed. |
| Narrative | The addition opens play rather than silently completing an active arc. |

Patch application preflights the complete operation list before mutation. Invalid ids,
unknown types, duplicate components, invalid fields, and broken references reject the patch
without leaving partial ECS edits. Semantic review still belongs to the operator.

## Integrate generated content after application

The generator can connect physical structure, but continuity often needs a human pass:

- add a sign at the old junction;
- update a map or directory;
- give only relevant characters a memory or rumor;
- add faction, household, or social edges;
- replace generic goals with motives tied to current world state;
- connect quests and objectives through authoritative relationships;
- define a schedule or reason the new location is visited;
- save and run health checks.

Do not broadcast the new location directly into every prompt. Let characters discover it
through persistent clues and appropriate knowledge.

## Correct by patching, not repeated roulette

If the proposal is mostly right, fix the wrong component, description, edge, or item in the
world editor. Repeatedly regenerating until one output happens to fit can create inconsistent
names, duplicated concepts, and expensive model churn.

If the same category of proposal is consistently wrong, improve the generation context,
plugin enrichment, or schema. Do not depend on a longer prompt to override unsupported
mechanics.

## Assisted-expansion review

- Generation is bounded to one anchored room, character, item, or event.
- A rollback exists before the inspector's generate-and-apply flow.
- Prompts describe narrative purpose, constraints, and exclusions.
- Proposal operations are reviewed when using MCP or other separate generation flows.
- Applied entities pass graph, containment, controller, and lifecycle checks.
- Manual integration makes the addition discoverable from the old world.
- The expansion is saved, playtested, and monitored for growth.

Return to [Expanding an existing world](world-building-expansion.md) for the complete loop.
