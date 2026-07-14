# MCP Playability TODO

Goal: make Bunnyland **fully playable through the MCP server alone**. An agent should never
need to read server source or `jq` a `world_snapshot` to take a valid action.

Findings below come from a live play session against `sandbox.bunnyland.dev` (claim →
look → move → use → say → take bun from vendor → eat bun). Each item names the likely
target file.

**Status (implemented and deployed):** the keystone read-side surface and command feedback
are live on the sandbox. See the items marked DONE.
New MCP tools: `character_view`, `room_view`, `character_commands`, `component_schema`,
`perceived_events`; `agent_prompt` gained an opt-in `include_entity_ids`; `send_command`
returns an outcome hint. Items marked FOLLOW-UP remain.

## Fix (blocking — a pure-MCP player hits a wall)

1. **[DONE] `agent_prompt` commands are not machine-actionable.**
   `character_view` returns structured `actions` (`command_type` + argument schema) with a
   `target_groups` map of resolved ids; `agent_prompt` now annotates affordances with ids
   when `include_entity_ids` is set (MCP sets it). Note: the literal
   `command_type:"move north"` no-op is unchanged — `send_command` still expects the verb +
   payload, which the structured surface now makes discoverable.
   → `src/bunnyland/mcp/server.py`, `src/bunnyland/prompts/builder.py`.

2. **[DONE] No entity ids exposed to the player surface.**
   `character_view.target_groups` resolves every targetable id; `agent_prompt` ids are
   opt-in. No more `world_snapshot` + `jq`.

3. **[DONE] Silent rejections look like successes.**
   `send_command` now returns a `note` that resolution is async and may reject;
   `perceived_events` surfaces the `CommandRejectedEvent` (with reason) once it resolves.
   It also fails fast: an unknown `command_type` is rejected at submit (pointing at
   `search_actions`) instead of being queued for a tick-later rejection.

4. **[DONE] Discoverable inventory consumption.**
   `character_view` exposes carried items in `target_groups.reachableItems`, and the
   canonical `eat` action is registered with an `item_id` argument. Agents can resolve it
   through action search and submit it through the normal command path.

## Add (missing capability)

5. **[DONE] Structured `available_actions` (highest leverage).**
   Delivered via `character_view` reusing `serialize_character_projection`
   (`ClientActionView` + `target_groups`). Progressive disclosure: the full ~400-action
   catalogue is too large to embed per call, so `character_view` omits it (keeps
   `target_groups` + `action_count`) and the catalogue is reached via `search_actions(query)`
   (the MCP equivalent of the TUI/Toon action search box) or `list_actions()` (everything).
   `search_actions` takes a `mode`: `"substring"` (default, matches anywhere -- the TUI box
   behaviour) or `"word"` (matches only where a word, split on hyphen/underscore/whitespace/
   punctuation, starts with the query, so `"eat"` no longer pulls in `creature`/`defeat`).
   `send_command` is callable straight from a resolved action + `target_groups`.

6. **[DONE] `examine {id}` tool.**
   `examine(agent_id, entity_id?)` returns curated component *values* for one perceivable
   entity (e.g. food nutrition/spoiled, door locked, container open). Omitting `entity_id`
   inspects yourself and additionally returns private needs/affect, status lines, and
   action/focus points -- examining another character never reveals their private state.
   → `serialize_examine` in `src/bunnyland/server/serialization.py`, tool in
   `src/bunnyland/mcp/server.py`.

7. **[FOLLOW-UP] Inventory-aware action surface (NPC-held items).**
   Own-inventory items are surfaced, but items held by *other* characters (the bun in the
   vendor) still are not listed; `take` reachability and projection differ.
   → builder.py reachability + `core/handlers/inventory.py` parity.

8. **[DONE] Action-result / outcome resource.**
   `perceived_events(agent_id, since, limit)` returns events the character caused or
   perceived (incl. command execution/rejection) with a `next_cursor` watermark; the
   streaming `bunnyland://agents/{id}/events` resource remains.

## Improve (quality / ergonomics)

9. **[DONE] `world_snapshot` is a 56k-char debug dump** that errors when returned inline.
   The play path now uses scoped projections (`character_view` = the player's own perceived
   room, the most common request; `room_view` for a specific room). Added a slim,
   admin-only `world_overview` (the room-network graph: ids, titles, exits, occupant/item
   counts) for the admin and web graph clients — gated by the `world:admin` scope on both
   the HTTP route (`GET /world/overview`) and the MCP tool (`world_overview_admin`). The raw
   ECS dump is now admin-only on every surface: `world_snapshot_admin` (MCP tool),
   `GET /world/snapshot`, and the `/world/updates` websocket all require a Bunnyland bearer
   token with `world:admin`, so a regular player cannot see the whole world through any
   door. The
   standard player clients (TUI, REPL) now read the per-room character/room projections
   instead of the snapshot.

10. **[DONE] Surface turn/tick timing.**
    `runtime_status` reports `tick_seconds` (real time between ticks), `time_scale`, and
    `game_seconds_per_tick`, so an agent paces its `perceived_events` polling to the loop.
    `send_command` also states resolution is async and points at the observe tools, and
    now returns `resolves_at_epoch` (the next-tick epoch the command is expected to resolve
    at); `character_commands` reports it per queued command too.

11. **[DONE] Canonical food verb.**
    `eat(item_id)` is the registered food action; `use` remains generic affordance dispatch.
    Action search, target groups, and the player hunger/inventory guides document the same
    contract.

12. **[DONE] Hunger feedback after eating.**
    The recent-context projection now logs `FoodEatenEvent`/`DrinkConsumedEvent` ("X ate
    the steamed bun." / "X drank from the water basin."), so eating/drinking is legible in
    the prompt's Recent context even when the hunger *band* does not change. (If a food's
    `satiety` is 0 the meter genuinely will not move -- that is a content value, separate
    from legibility; `examine`/`perceived_events` expose the numeric change.)

13. **[PARTIAL] Duplicate / co-directional exits are confusing.**
    With `include_entity_ids` the prompt's `move` lines and `character_view.target_groups`
    now carry destination ids, so same-named exits are distinguishable. FOLLOW-UP: the
    narrative `Exits:` list still repeats `south, south` without destinations.
    → builder.py exit rendering.

14. **[FOLLOW-UP] Player docs for MCP play.**
    Now that actions are structured, add a `docs/player/` (or `docs/admin/`) guide for
    driving a character through the MCP tools end to end.
