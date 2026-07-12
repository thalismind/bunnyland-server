# Action availability — client implementation guide

This guide is for client/frontend developers (e.g. the `bunnyland-web` repo). It explains
the per-action availability fields now exposed on the character projection and the
synchronous rejection now returned by the command submit endpoint, and how to use them.

## TL;DR

- The character projection (`GET /world/character/{id}`) now tells you, **per action**,
  whether the character can take it right now: enough points, a valid target, and any
  required skill/item. Use it to enable/disable/annotate buttons in the action bar.
- The submit endpoint (`POST /world/commands`) now **rejects obviously-invalid commands
  immediately** with a `reason`, instead of always queuing. Surface that reason inline.
- All new fields are additive with safe defaults; nothing breaks if you ignore them, but
  you should adopt both for a responsive UI.
- The serialized `actions` and `target_groups` are the only frontend action catalogue. Do
  not ship static verb lists or infer actions when registry metadata is unavailable; render
  an empty/disabled action state until a fresh projection arrives.

The availability flags are a **coarse hint** for the UI. The server (the command handler,
on the next world tick) remains the source of truth and can still reject a command that
looked available — see [Trust model](#trust-model).

---

## 1. Reading availability from the character projection

`GET /world/character/{id}` → `CharacterProjectionResponse`. The relevant parts:

```jsonc
{
  "world_epoch": 1234,
  "character_id": "entity:42",
  "points": { "action": 3.0, "action_max": 5.0, "focus": 1.0, "focus_max": 3.0 },
  "target_groups": {
    "exits":          [ { "id": "entity:7",  "label": "north: North Tunnel", "kind": "exit" } ],
    "roomItems":      [ { "id": "entity:9",  "label": "brass key",  "kind": "item" } ],
    "inventory":      [ { "id": "entity:11", "label": "torch",      "kind": "item" } ],
    "characters":     [ { "id": "entity:12", "label": "Hazel",      "kind": "character" } ],
    "reachable":      [ /* room + inventory, all kinds */ ],
    "reachableItems": [ /* reachable, items only */ ]
  },
  "actions": [
    {
      "command_type": "pick-lock",
      "tool_name": "pick_lock",
      "title": "Pick Lock",
      "description": "...",
      "lane": "world",
      "cost": { "action": 1, "focus": 0 },
      "arguments": [
        { "key": "lock_id", "title": "Lock", "kind": "entity",
          "required": false, "target_group": "reachableItems" }
      ],

      // --- NEW per-character availability fields ---
      "available": false,
      "enough_action_points": true,
      "enough_focus_points": true,
      "has_required_target": true,
      "meets_requirements": false,
      "unavailable_reason": "missing a required skill or item"
    }
  ]
}
```

### The new fields on each action

| Field | Type | Meaning |
|---|---|---|
| `available` | bool | Overall: true only when the action can be taken right now. AND of the four below plus character-level state (asleep/downed/etc.). **Use this to enable/disable the button.** |
| `enough_action_points` | bool | `points.action >= cost.action`. |
| `enough_focus_points` | bool | `points.focus >= cost.focus`. |
| `has_required_target` | bool | Every *required* entity argument has at least one candidate in the room/inventory. False ⇒ there's nothing valid to act on. |
| `meets_requirements` | bool | Coarse capability gate — does the character have the needed skill/item subsystem (e.g. knows any spell, has a skill set). |
| `unavailable_reason` | string | Human-readable reason the action is unavailable; `""` when available. The first failing check. |

All flags default to `true` / `""`, so an action with no special needs (e.g. `look`,
`say`, `move`) is simply `available: true`.

> `unavailable_reason` values are stable English strings (e.g. `"not enough action
> points"`, `"not enough focus points"`, `"no valid target available"`, `"missing a
> required skill or item"`, `"character is asleep"`). Show them directly, or map them to
> localized/iconographic equivalents — but treat the booleans, not the string, as the
> machine-readable signal.

### Suggested rendering

```ts
for (const action of projection.actions) {
  const btn = renderActionButton(action);
  btn.disabled = !action.available;
  if (!action.available) {
    btn.title = action.unavailable_reason;            // tooltip
    if (!action.enough_action_points || !action.enough_focus_points) {
      btn.classList.add("needs-points");              // e.g. dim + show cost in red
    }
    if (!action.has_required_target) {
      btn.classList.add("no-target");                 // e.g. greyed, "nothing to use"
    }
    if (!action.meets_requirements) {
      btn.classList.add("locked");                     // e.g. lock icon
    }
  }
}
```

Pick the treatment per flag if you want richer UX (e.g. a points-starved action can stay
clickable to show "regenerating…", while a `meets_requirements: false` action is hard
locked). The single rule that always holds: **don't submit an action whose `available`
is false** — it will be rejected.

### Populating argument pickers

For actions that take an entity argument, each argument carries a `target_group` naming
which list in `target_groups` holds the candidates. Build the target dropdown from
`target_groups[argument.target_group]` (each entry has `id`, `label`, `kind`). Submit the
chosen `id` as the payload value for that argument key. This is unchanged by this feature;
it's the same mechanism `has_required_target` is computed from.

---

## 2. Submitting commands (synchronous rejection)

`POST /world/commands` with `CommandRequest`:

```jsonc
{
  "character_id": "entity:42",
  "controller_id": "entity:99",
  "controller_generation": 3,
  "command_type": "pick-lock",          // use the action's command_type
  "payload": { "lock_id": "entity:9" }, // arg key -> chosen target id / value
  "cost": { "action": 1, "focus": 0 },  // copy from the action's cost
  "lane": "world",                       // copy from the action's lane ("world" | "focus")
  "on_insufficient_points": "queue"      // "queue" (default) or "deny"
}
```

Response is `CommandResponse` (HTTP **202**, same as before):

```jsonc
{ "queued": true,  "command_id": "abc123", "reason": "" }   // accepted
{ "queued": false, "command_id": "abc123", "reason": "missing required argument: lock_id" } // rejected at submit
```

### What changed

- `reason` is a **new** field (always present; `""` when accepted).
- `queued` can now be `false`: the command was rejected at submission and **not** queued.
- The HTTP status stays `202` in both cases — **branch on the `queued` field, not the
  status code.**

```ts
const res = await postCommand(req);
const body = await res.json();
if (!body.queued) {
  showInlineError(body.reason);   // e.g. "missing required argument: lock_id"
  return;
}
trackPending(body.command_id);    // accepted; resolves on a later tick
```

### What gets rejected at submit (vs. later)

Submit-time rejection is deliberately **structural** — it catches problems that won't fix
themselves by waiting:

- character can't act (dead / suspended / downed / asleep)
- unknown/unhandled command type
- a **missing required argument**
- an unmet capability requirement (`meets_requirements` would be false)
- insufficient points **only** when `on_insufficient_points: "deny"`

It does **not** reject on target reachability/existence, and it does **not** reject
insufficient points under `"queue"` (those wait for point regen and resolve on a tick).
Those outcomes still arrive asynchronously — see below.

---

## 3. Trust model — availability is a hint, the tick is the truth

The projection flags and submit checks are coarse and cheap. The authoritative validation
runs inside the command handler on the next world tick. A command that passed submit can
still be rejected there (e.g. the specific target moved out of reach, a skill level was
too low for *this* spell, an item had no charges). So:

1. **Use `available` to gate the UI** and `CommandResponse.reason` for instant feedback on
   structurally-bad submits.
2. **Still listen for the asynchronous outcome** of accepted commands. Poll/stream recent
   events and watch for:
   - a successful execution event, or
   - a `CommandRejectedEvent` carrying a `reason` (same vocabulary as `unavailable_reason`).
   You can also see still-pending commands via `GET /world/character/{id}/commands`.

Don't treat `queued: true` as "it worked" — treat it as "accepted for processing."

---

## 4. Live updates, fallback, and staleness

Availability is computed against the world at the moment the projection was built
(`world_epoch`). Points regenerate, targets move, and state changes every tick, so:

- Prefer the claim-authenticated player stream at
  `WS /world/character/{character_id}/updates`. Send the claim id and secret in the first
  `authenticate` frame, never in the URL. Event, invalidation, resync, and heartbeat frames
  tell the client when to refresh projections.
- Reconnect with bounded backoff. While disconnected, use
  `GET /world/character/{character_id}/events/recent` with the same claim proof, deduplicate
  frames, and refresh the projection after meaningful events or invalidations.
- Local clients may remain polling-only, but remote TUI, REPL, Toon, chat, and character
  sheet surfaces should share this player-scoped stream/fallback behavior.
- If you compare epochs, a newer `world_epoch` means availability may have changed.

---

## 5. MCP clients

The MCP `send_command` tool mirrors this: on early rejection it returns
`{ "ok": false, "queued": false, "reason": "...", "note": "..." }`; on acceptance it
returns the existing `{ "ok": true, "queued": true, "command_id": ..., "note": ... }`.
Agents should read `reason`, fix the issue, and resend rather than waiting for a tick.

---

## Quick checklist for the frontend

- [ ] Disable action buttons where `available === false`; tooltip = `unavailable_reason`.
- [ ] Optionally style by specific flag (points / target / requirement).
- [ ] Build argument pickers from `target_groups[argument.target_group]`.
- [ ] On submit, branch on `CommandResponse.queued`; show `reason` when `false`.
- [ ] Keep listening for async execution / `CommandRejectedEvent` on accepted commands.
- [ ] Subscribe to the player-scoped stream; reconnect and use the recent-event fallback.
- [ ] Refresh the projection after commands resolve to keep flags current.
- [ ] Render no actions when registry-derived metadata is unavailable; never use a static
      frontend verb catalogue.
