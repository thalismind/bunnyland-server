# MCP-controlled play

An MCP client can play Bunnyland using only the scoped play tools. The normal loop is:

```text
list characters -> claim -> look -> find an action -> send -> observe -> look again
```

The server remains authoritative. Tool calls discover valid actions and targets, but commands
still spend points, enter a queue, and resolve on a later world tick.

## Connect

Configure a Streamable HTTP MCP connection to the server's endpoint:

- local server: `http://127.0.0.1:8765/v1/mcp/`
- hosted server: `https://sandbox.bunnyland.dev/api/v1/mcp/`

The connection needs a bearer token with `world:play`. Put the token in the MCP client's
protected header or credential configuration as `Authorization: Bearer ...`; never pass it as
a tool argument. Server operators can follow [Connect a local agent to Bunnyland
MCP](../../admin/mcp-local-agent.md) to start MCP and provision the token.

Use one stable `client_id` for the session. If the server enforces a client-ID allowlist, the
same value must be configured as the `X-Bunnyland-Client-Id` request header.

## Choose and claim a character

Call `play_list_characters`, choose a character by id or name, then claim it:

```json
{
  "tool": "play_claim_character",
  "arguments": {
    "client_id": "my-mcp-player",
    "character_id": "<character-id>",
    "label": "My MCP player"
  }
}
```

Keep the returned `claim_id` and `claim_secret` in protected session state. They identify the
character claim; they are separate from the bearer token that grants API access. Supply them
to later claim-scoped calls when the MCP client does not carry the claim secret in its request
header.

If a retained claim no longer has active control, call `play_reclaim_character` with those
credentials. Do not create a second claim for the same session.

## Read the current situation

Start with `play_look` for a concise room summary. Use `play_get_projection` when you need the
machine-readable room, inventory, points, exits, and `target_groups`. Each target entry supplies
the exact entity id expected by action payloads.

Call `play_examine` with an interesting visible entity id to inspect public details such as food
value, portability, or container state. Omit `entity_id` to inspect your own detailed status,
needs, and action/focus points.

The projection deliberately omits the full action catalogue. Find a verb with
`play_search_actions`; `mode: "word"` is useful for short verbs such as `eat`. Then call
`play_action_help` to see its cost, availability, argument schema, and valid targets.

## Send and observe an action

For example, after resolving a portable item's id from `target_groups.reachableItems`:

```json
{
  "tool": "play_send_command",
  "arguments": {
    "client_id": "my-mcp-player",
    "claim_id": "<claim-id>",
    "claim_secret": "<claim-secret>",
    "command_type": "take",
    "payload": {"item_id": "<item-id>"}
  }
}
```

An accepted response means the command is queued, not completed. Save the current event cursor,
then call `play_recent_events` with `since` until the command produces an execution event or a
`CommandRejectedEvent`. Pass the returned `next_cursor` into the next poll. Use
`play_pending_commands` to check whether the command is still queued, and
`play_cancel_command` if it must be withdrawn before resolution.

After an outcome, call `play_look` or `play_get_projection` again rather than assuming the world
changed as requested. `play_what_changed` provides another bounded summary when you retained a
previous `world_epoch` watermark.

Repeat the same discovery loop for movement, conversation, and needs:

- resolve an exit id from `target_groups.exits`, then inspect the `move` action;
- send `say` with its text payload to speak in the room;
- take food, inspect it, and use the canonical `eat` action with its item id;
- treat submission errors and later `CommandRejectedEvent` reasons as authoritative, refresh the
  projection, and choose another valid action.

## Finish the session

`play_release_control` hands active control to the requested fallback while retaining the claim,
so the same client can later reclaim the character. `play_release_claim` gives up claim ownership
without changing whichever controller is currently active. Use both deliberately when ending a
session; do not discard claim credentials while you still intend to resume it.
