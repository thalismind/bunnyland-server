# MCP Playability TODO

Goal: make Bunnyland **fully playable through the MCP server alone**. An agent should never
need to read server source or `jq` a `world_snapshot` to take a valid action.

Findings below come from a live play session against `sandbox.bunnyland.dev` (claim →
look → move → use → say → take bun from vendor → eat bun). Each item names the likely
target file.

**Status (local, not yet deployed to the sandbox):** the keystone read-side surface and
command feedback landed — see [`docs/developer/mcp-playability-todo`] items marked DONE.
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

4. **[PARTIAL] No discoverable way to consume inventory items.**
   `character_view` now lists every available action and `target_groups.reachableItems`
   includes carried items, so a registered consume verb with an `item_id` arg is
   discoverable. FOLLOW-UP: the catalogue still has no `eat`; the canonical `consume` vs
   `use` ambiguity (Improve #11) is unresolved.

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

6. **[FOLLOW-UP] `examine {id}` tool.**
   Not added. `component_schema` explains component *types*, and `character_view`/`room_view`
   list entities, but there is still no per-entity structured detail tool.
   → `src/bunnyland/mcp/server.py`.

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
   counts) for the admin and web graph clients — gated on both the HTTP route
   (`GET /world/overview`, `X-Bunnyland-Admin-Token`) and the MCP tool
   (`world_overview_admin`). `world_snapshot` remains the raw ECS dump for admin/debug.
   FOLLOW-UP: `world_snapshot` / `GET /world/snapshot` are still ungated — a player using
   them sees everything, which is also cheating; consider gating them too.

10. **[PARTIAL] Surface turn/tick timing.**
    `send_command` now states resolution is async/turn-based and points at
    `perceived_events`/`character_commands`. FOLLOW-UP: still no explicit tick cadence,
    queue position, or "resolves at epoch".
    → `runtime_status` + `send_command` response.

11. **[FOLLOW-UP] Disambiguate the consume verb.**
    Confirm canonical food verb (`consume` vs `use`) and document it; the test queued both
    so the winner is unknown. The vendor has a second steamed bun for a clean single-verb
    test.
    → `core/handlers/` + player docs.

12. **[FOLLOW-UP] Hunger feedback after eating.**
    Eating flipped mood to *content* but the `starving` condition did not clear on that
    tick. Verify whether hunger is slow-resolving or food value is too low, and make the
    effect legible to the player.
    → lifesim hunger/food handling + prompt status lines.

13. **[PARTIAL] Duplicate / co-directional exits are confusing.**
    With `include_entity_ids` the prompt's `move` lines and `character_view.target_groups`
    now carry destination ids, so same-named exits are distinguishable. FOLLOW-UP: the
    narrative `Exits:` list still repeats `south, south` without destinations.
    → builder.py exit rendering.

14. **[FOLLOW-UP] Player docs for MCP play.**
    Now that actions are structured, add a `docs/player/` (or `docs/admin/`) guide for
    driving a character through the MCP tools end to end.
