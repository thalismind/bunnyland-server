"""Streamable HTTP MCP server mounted into the existing FastAPI app."""

from __future__ import annotations

import json
import os
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from pydantic import AnyUrl
from relics import EntityId

from ..claims import (
    claimable_characters,
    controlled_character,
    is_child_character,
    match_character_by_name,
    matching_controller,
)
from ..core import (
    CharacterComponent,
    ControlledBy,
    IdentityComponent,
    LLMControllerComponent,
    MCPControllerComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    spawn_entity,
)
from ..core.commands import CommandCost, Lane, OnInsufficientPoints, build_submitted_command
from ..core.ecs import container_of, parse_entity_id
from ..core.events import CharacterClaimedEvent, DomainEvent
from ..plugins.builtin import MCP
from ..prompts import PromptBuilder, render_prompt
from ..server.models import (
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldGenerateRequest,
    WorldGenerationStatusResponse,
    WorldItemGenerationRequest,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
)
from ..server.schema import world_schema
from ..server.serialization import (
    event_message,
    serialize_action_search,
    serialize_character_projection,
    serialize_character_queued_commands,
    serialize_examine,
    serialize_room_projection,
    serialize_world,
    serialize_world_overview,
)

if TYPE_CHECKING:  # pragma: no cover - import-only typing aliases
    from ..core.world_actor import WorldActor
    from ..engine import GameLoop
    from ..persistence import WorldMeta
    from ..plugins.model import Plugin
    from ..server.models import (
        WorldCharacterGenerationResponse,
        WorldEventGenerationResponse,
        WorldGenerateResponse,
        WorldItemGenerationResponse,
        WorldPatchResponse,
        WorldRoomGenerationResponse,
    )
    from ..worldgen import GenOptions

MCP_MOUNT_PATH = "/mcp"
ADMIN_TOKEN_ENV = "BUNNYLAND_MCP_ADMIN_TOKEN"
EVENTS_RESOURCE_URI = "bunnyland://events/recent"


def mcp_enabled(plugins: Sequence[Plugin] | None) -> bool:
    return any(plugin.id == MCP or plugin.id.endswith(".mcp") for plugin in plugins or ())


def _agent_events_uri(agent_id: str) -> str:
    return f"bunnyland://agents/{quote(agent_id, safe='')}/events"


def _agent_prompt_uri(agent_id: str) -> str:
    return f"bunnyland://agents/{quote(agent_id, safe='')}/prompt"


def _agent_id_from_uri(uri: str, suffix: str) -> str | None:
    prefix = "bunnyland://agents/"
    if not uri.startswith(prefix) or not uri.endswith(suffix):
        return None
    encoded = uri[len(prefix) : -len(suffix)]
    return unquote(encoded)


def _active_controller_kind(actor: WorldActor, character) -> str:
    for _edge, controller_id in character.get_relationships(ControlledBy):
        if not actor.world.has_entity(controller_id):
            continue
        controller = actor.world.get_entity(controller_id)
        if controller.has_component(MCPControllerComponent):
            return "MCP controller"
    return "other"


def _character_summary(actor: WorldActor, character) -> dict[str, Any]:
    identity = character.get_component(IdentityComponent)
    suspended = character.has_component(SuspendedComponent)
    return {
        "character_id": str(character.id),
        "name": identity.name,
        "kind": identity.kind,
        "suspended": suspended,
        "controller_status": _active_controller_kind(actor, character)
        if not suspended
        else "suspended",
    }


def list_mcp_characters(actor: WorldActor) -> list[dict[str, Any]]:
    characters = actor.world.query().with_all([CharacterComponent, IdentityComponent])
    return [_character_summary(actor, character) for character in characters.execute_entities()]


@dataclass(frozen=True)
class _SubscribedSession:
    session: Any

    def __hash__(self) -> int:
        return id(self.session)


class MCPEventBridge:
    """Expose Bunnyland domain events as MCP-readable resources with update notifications."""

    def __init__(self, actor: WorldActor, *, recent_limit: int = 200) -> None:
        self.actor = actor
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_limit)
        self._subscriptions: dict[str, set[_SubscribedSession]] = {}
        self._seq = 0
        actor.bus.subscribe(DomainEvent, self.record)

    def close(self) -> None:
        self.actor.bus.unsubscribe(DomainEvent, self.record)
        self._subscriptions.clear()

    def recent_messages(self) -> list[dict[str, Any]]:
        return list(self._recent)

    def recent_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        controlled = mcp_controlled_character(self.actor, agent_id)
        if controlled is None:
            return []
        character_id = str(controlled[0])
        filtered: list[dict[str, Any]] = []
        for message in self._recent:
            event = message.get("data", {}).get("event", {})
            if event.get("actor_id") == character_id:
                filtered.append(message)
        return filtered

    def perceived_for_agent(
        self, agent_id: str, *, since: int | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Return recent events the agent's character caused or perceived in its room.

        ``since`` is a watermark cursor: only events recorded after it are returned. The
        response carries ``next_cursor`` to pass as ``since`` on the next poll so streaming
        gaps and missed notifications can be reconciled.
        """

        controlled = mcp_controlled_character(self.actor, agent_id)
        if controlled is None:
            return {"ok": False, "agent_id": agent_id, "events": [], "next_cursor": since or 0}
        character_id = str(controlled[0])
        room_id = container_of(self.actor.world.get_entity(controlled[0]))
        room_key = str(room_id) if room_id is not None else None

        def perceived(message: dict[str, Any]) -> bool:
            event = message.get("data", {}).get("event", {})
            if event.get("actor_id") == character_id:
                return True
            return room_key is not None and event.get("room_id") == room_key

        matches = [
            message
            for message in self._recent
            if (since is None or message.get("seq", 0) > since) and perceived(message)
        ]
        matches.sort(key=lambda message: message.get("seq", 0))
        page = matches[: max(0, limit)] if limit else matches
        if page and len(page) < len(matches):
            next_cursor = page[-1].get("seq", self._seq)
        else:
            next_cursor = self._seq
        return {
            "ok": True,
            "agent_id": agent_id,
            "events": page,
            "next_cursor": next_cursor,
        }

    def subscribe(self, uri: str, session: Any) -> None:
        self._subscriptions.setdefault(uri, set()).add(_SubscribedSession(session))

    def unsubscribe(self, uri: str, session: Any) -> None:
        sessions = self._subscriptions.get(uri)
        if not sessions:
            return
        sessions.discard(_SubscribedSession(session))
        if not sessions:
            self._subscriptions.pop(uri, None)

    async def record(self, event: DomainEvent) -> None:
        message = event_message(event)
        self._seq += 1
        message["seq"] = self._seq
        self._recent.append(message)
        await self._notify_changed_resources(message)

    async def _notify_changed_resources(self, message: dict[str, Any]) -> None:
        event = message.get("data", {}).get("event", {})
        event_actor_id = event.get("actor_id")
        uris: set[str] = {EVENTS_RESOURCE_URI}

        for uri in self._subscriptions:
            if _agent_id_from_uri(uri, "/prompt") is not None:
                # Prompt context can change for indirect reasons: room events, nearby
                # actors, conditions, and point regeneration can all alter prompt text.
                uris.add(uri)
                continue
            agent_id = _agent_id_from_uri(uri, "/events")
            if agent_id is None:
                continue
            controlled = mcp_controlled_character(self.actor, agent_id)
            if controlled is not None and str(controlled[0]) == event_actor_id:
                uris.add(uri)

        for uri in uris:
            await self._notify_uri(uri)

    async def _notify_uri(self, uri: str) -> None:
        sessions = self._subscriptions.get(uri)
        if not sessions:
            return
        stale: list[_SubscribedSession] = []
        for subscribed in tuple(sessions):
            try:
                await subscribed.session.send_resource_updated(AnyUrl(uri))
            except Exception:
                stale.append(subscribed)
        for subscribed in stale:
            sessions.discard(subscribed)
        if not sessions:
            self._subscriptions.pop(uri, None)


def _is_child_character(character) -> bool:
    return is_child_character(character)


def _match_character(
    actor: WorldActor,
    character_name: str | None,
    character_id: str | None,
    *,
    allow_child_claims: bool,
):
    characters = list(
        actor.world.query().with_all([CharacterComponent, IdentityComponent]).execute_entities()
    )
    if character_id:
        entity_id = parse_entity_id(character_id)
        if entity_id is not None and actor.world.has_entity(entity_id):
            character = actor.world.get_entity(entity_id)
            if character.has_component(CharacterComponent):
                return character
        raise RuntimeError(f"no character with id {character_id!r} exists in the world")
    if character_name:
        matched = match_character_by_name(characters, character_name)
        if matched is not None:
            return matched
        names = ", ".join(
            character.get_component(IdentityComponent).name for character in characters
        )
        raise RuntimeError(
            f"no character named {character_name!r} exists in the world. "
            f"Available characters: {names}"
        )
    claimable = claimable_characters(characters, allow_child_claims=allow_child_claims)
    if claimable:
        return claimable[0]
    raise RuntimeError("no suspended claimable character exists in the world")


def _mcp_controller_for(actor: WorldActor, agent_id: str):
    return matching_controller(
        actor,
        MCPControllerComponent,
        lambda controller: controller.agent_id == agent_id,
    )


def mcp_controlled_character(actor: WorldActor, agent_id: str):
    return controlled_character(
        actor,
        MCPControllerComponent,
        lambda controller: controller.agent_id == agent_id,
    )


def assign_mcp_controller(
    actor: WorldActor,
    *,
    agent_id: str,
    character_name: str | None = None,
    character_id: str | None = None,
    label: str = "",
    allow_child_claims: bool = False,
) -> dict[str, Any]:
    """Assign an MCP controller to a named/id character, or the first suspended one."""

    agent_id = agent_id.strip()
    if not agent_id:
        raise RuntimeError("agent_id is required")
    character = _match_character(
        actor,
        character_name,
        character_id,
        allow_child_claims=allow_child_claims,
    )
    if _is_child_character(character) and not allow_child_claims:
        name = character.get_component(IdentityComponent).name
        raise RuntimeError(f"{name} is a child character and cannot be claimed on this server")

    controller = _mcp_controller_for(actor, agent_id)
    if controller is None:
        controller = spawn_entity(
            actor.world,
            [MCPControllerComponent(agent_id=agent_id, label=label.strip())],
        )

    generation = actor.assign_controller(character.id, controller.id)
    if character.has_component(SuspendedComponent):
        character.remove_component(SuspendedComponent)
    identity = character.get_component(IdentityComponent)
    return {
        "ok": True,
        "agent_id": agent_id,
        "character_id": str(character.id),
        "character_name": identity.name,
        "controller_id": str(controller.id),
        "controller_generation": generation,
    }


def release_mcp_controller(
    actor: WorldActor,
    *,
    agent_id: str,
    mode: str = "suspend",
    reason: str = "released by MCP client",
    model: str | None = None,
    provider: str = "ollama",
) -> dict[str, Any]:
    """Release an MCP-controlled character to suspended or LLM control."""

    found = mcp_controlled_character(actor, agent_id)
    if found is None:
        raise RuntimeError("agent is not controlling a character yet")
    character_id, old_controller_id, _generation = found
    character = actor.world.get_entity(character_id)
    identity = character.get_component(IdentityComponent)

    if mode == "suspend":
        controller = spawn_entity(actor.world, [SuspendedControllerComponent(reason=reason)])
        generation = actor.suspend(character.id, controller.id, reason=reason)
        controller_kind = "suspended"
    elif mode == "llm":
        controller = spawn_entity(
            actor.world,
            [
                LLMControllerComponent(
                    profile_name="default",
                    model=model
                    or os.environ.get("BUNNYLAND_CHARACTER_MODEL", "deepseek-v4-flash"),
                    provider=provider,
                )
            ],
        )
        generation = actor.assign_controller(character.id, controller.id)
        if character.has_component(SuspendedComponent):
            character.remove_component(SuspendedComponent)
        controller_kind = "llm"
    else:
        raise RuntimeError("mode must be 'suspend' or 'llm'")

    old_controller = actor.world.get_entity(old_controller_id)
    if old_controller.has_component(MCPControllerComponent):
        old_controller.remove_component(MCPControllerComponent)
    return {
        "ok": True,
        "agent_id": agent_id,
        "character_id": str(character.id),
        "character_name": identity.name,
        "controller_id": str(controller.id),
        "controller_generation": generation,
        "controller_kind": controller_kind,
    }


def render_mcp_agent_prompt(
    actor: WorldActor,
    *,
    agent_id: str,
    fragment_providers: Sequence[Any] = (),
    persona_providers: Sequence[Any] = (),
) -> dict[str, Any]:
    found = mcp_controlled_character(actor, agent_id)
    if found is None:
        raise RuntimeError("agent is not controlling a character yet")
    character_id, _controller_id, generation = found
    builder = PromptBuilder(
        actor.world,
        fragment_providers=fragment_providers,
        persona_providers=persona_providers,
        include_entity_ids=True,
    )
    context = builder.build(character_id, epoch=actor.epoch)
    return {
        "ok": True,
        "agent_id": agent_id,
        "character_id": str(character_id),
        "controller_generation": generation,
        "world_epoch": actor.epoch,
        "prompt": render_prompt(context),
    }


def _require_admin_token(supplied: str | None, configured: str | None) -> None:
    expected = (configured or os.environ.get(ADMIN_TOKEN_ENV) or "").strip()
    if not expected:
        raise PermissionError(f"{ADMIN_TOKEN_ENV} is not configured")
    if supplied != expected:
        raise PermissionError("invalid MCP admin token")


def _controlled_or_requested_character(
    actor: WorldActor, agent_id: str, character_id: str | None
) -> tuple[EntityId, EntityId, int]:
    if character_id is None:
        found = mcp_controlled_character(actor, agent_id)
        if found is None:
            raise RuntimeError("agent is not controlling a character yet")
        return found

    requested_id = parse_entity_id(character_id)
    if requested_id is None or not actor.world.has_entity(requested_id):
        raise RuntimeError(f"character {character_id!r} does not exist")
    found = mcp_controlled_character(actor, agent_id)
    if found is None or found[0] != requested_id:
        raise RuntimeError("agent does not control the requested character")
    return found


def create_bunnyland_mcp_app(
    *,
    actor: WorldActor,
    meta: WorldMeta,
    loop: GameLoop | None,
    admin_token: str | None,
    patch_world: Callable[[WorldPatchRequest], Awaitable[WorldPatchResponse]],
    generate_world: Callable[[WorldGenerateRequest], Awaitable[WorldGenerateResponse]],
    generation_status: Callable[[], Awaitable[WorldGenerationStatusResponse]],
    generate_room: Callable[[WorldRoomGenerationRequest], WorldRoomGenerationResponse],
    generate_character: Callable[
        [WorldCharacterGenerationRequest], WorldCharacterGenerationResponse
    ],
    generate_item: Callable[[WorldItemGenerationRequest], WorldItemGenerationResponse],
    generate_event: Callable[[WorldEventGenerationRequest], WorldEventGenerationResponse],
    fragment_providers: Sequence[Any] = (),
    persona_providers: Sequence[Any] = (),
    worldgen_options: GenOptions | None = None,
):
    """Create the ASGI MCP app.

    Importing the SDK here keeps the ``mcp`` extra optional for normal Bunnyland installs.
    """

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.server.fastmcp.exceptions import ToolError
    except ImportError as exc:  # pragma: no cover - exercised only without optional deps
        raise RuntimeError(
            "the MCP server requires the 'mcp' extra: pip install bunnyland[mcp]"
        ) from exc

    mcp = FastMCP(
        "Bunnyland",
        instructions=(
            "Control a Bunnyland character, inspect the world, and perform "
            "admin-authorized world patching or generation."
        ),
        stateless_http=False,
        json_response=True,
        streamable_http_path="/",
    )
    event_bridge = MCPEventBridge(actor)

    low_server = mcp._mcp_server
    original_get_capabilities = low_server.get_capabilities

    def get_capabilities(notification_options, experimental_capabilities):
        capabilities = original_get_capabilities(
            notification_options,
            experimental_capabilities,
        )
        if capabilities.resources is not None:
            capabilities.resources.subscribe = True
            capabilities.resources.listChanged = True
        return capabilities

    low_server.get_capabilities = get_capabilities

    @low_server.subscribe_resource()
    async def subscribe_resource(uri: AnyUrl) -> None:
        context = mcp.get_context()
        event_bridge.subscribe(str(uri), context.session)

    @low_server.unsubscribe_resource()
    async def unsubscribe_resource(uri: AnyUrl) -> None:
        context = mcp.get_context()
        event_bridge.unsubscribe(str(uri), context.session)

    def admin(supplied: str | None) -> None:
        try:
            _require_admin_token(supplied, admin_token)
        except PermissionError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.resource(
        EVENTS_RESOURCE_URI,
        name="recent_world_events",
        description="Recent Bunnyland domain events.",
        mime_type="application/json",
    )
    def recent_world_events_resource() -> str:
        return json.dumps({"ok": True, "events": event_bridge.recent_messages()})

    @mcp.resource(
        "bunnyland://agents/{agent_id}/events",
        name="agent_events",
        description="Recent Bunnyland domain events for an MCP-controlled agent character.",
        mime_type="application/json",
    )
    def agent_events_resource(agent_id: str) -> str:
        return json.dumps(
            {
                "ok": True,
                "agent_id": agent_id,
                "events": event_bridge.recent_for_agent(agent_id),
            }
        )

    @mcp.resource(
        "bunnyland://agents/{agent_id}/prompt",
        name="agent_prompt",
        description="Current Bunnyland prompt text for an MCP-controlled agent character.",
        mime_type="text/plain",
    )
    def agent_prompt_resource(agent_id: str) -> str:
        return render_mcp_agent_prompt(
            actor,
            agent_id=agent_id,
            fragment_providers=fragment_providers,
            persona_providers=persona_providers,
        )["prompt"]

    @mcp.tool()
    def list_characters() -> dict[str, Any]:
        """List claimable and controlled characters in the current world."""

        return {"ok": True, "characters": list_mcp_characters(actor)}

    @mcp.tool()
    def world_snapshot() -> dict[str, Any]:
        """Return the full raw ECS world snapshot (large; admin/debug and persistence).

        This is the heavy dump of every entity and component. For normal use prefer the
        scoped projections: ``character_view``/``room_view`` for a play-facing slice and
        ``world_overview_admin`` for the room-network map.
        """

        return serialize_world(actor, meta)

    @mcp.tool()
    def world_overview_admin(admin_token: str) -> dict[str, Any]:
        """Return a slim, admin-only map of the whole room network (admin token required).

        Rooms with ids, titles, exits, and occupant/item counts -- the privileged graph the
        admin and web graph clients render. Withheld from players: seeing the full map would
        be cheating. For a player's own view use ``character_view`` (their perceived room).
        """

        admin(admin_token)
        return serialize_world_overview(actor).model_dump()

    @mcp.tool()
    def runtime_status() -> dict[str, Any]:
        """Return current runtime status and the tick cadence for the game loop.

        ``tick_seconds`` is the real time between ticks -- i.e. roughly how long to wait
        before polling perceived_events for a queued command's outcome. ``time_scale`` is
        in-world seconds per real second, so each tick advances the world clock by
        ``game_seconds_per_tick`` (``world_epoch`` units).
        """

        tick = getattr(loop, "tick_seconds", None)
        scale = getattr(loop, "time_scale", None)
        tick_seconds = float(tick) if tick is not None else None
        time_scale = float(scale) if scale is not None else None
        return {
            "ok": True,
            "world_epoch": actor.epoch,
            "running": bool(loop.running) if loop is not None else False,
            "paused": bool(loop.paused) if loop is not None else False,
            "tick_seconds": tick_seconds,
            "time_scale": time_scale,
            "game_seconds_per_tick": (
                tick_seconds * time_scale
                if tick_seconds is not None and time_scale is not None
                else None
            ),
        }

    @mcp.tool()
    def agent_prompt(agent_id: str) -> dict[str, Any]:
        """Return the current Bunnyland prompt for an MCP-controlled agent."""

        try:
            return render_mcp_agent_prompt(
                actor,
                agent_id=agent_id,
                fragment_providers=fragment_providers,
                persona_providers=persona_providers,
            )
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def character_view(agent_id: str, character_id: str | None = None) -> dict[str, Any]:
        """Return a structured, play-facing view for the agent's character.

        Unlike ``agent_prompt`` (narrative text), this returns machine-readable data: the
        room and its entities, inventory, action/focus points, and ``target_groups``
        resolving every targetable entity id. The full action catalogue is omitted here to
        keep the view small (progressive disclosure); use ``search_actions``/``list_actions``
        to find a verb and its argument schema, then read each argument's entity id from
        ``target_groups[argument.target_group]`` and call ``send_command``.
        """

        try:
            character, _controller, _generation = _controlled_or_requested_character(
                actor, agent_id, character_id
            )
            data = serialize_character_projection(actor, str(character)).model_dump()
            actions = data.pop("actions", [])
            data["action_count"] = len(actions)
            data["actions_hint"] = (
                "Action catalogue omitted; call search_actions(query) or list_actions(), "
                "then resolve ids from target_groups."
            )
            return data
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def search_actions(
        query: str = "", limit: int = 30, mode: str = "substring"
    ) -> dict[str, Any]:
        """Search the action catalogue -- the MCP equivalent of the clients' action box.

        Matches ``query`` against each action's command_type, title, and tool name,
        returning a slim, paged list of actions with their argument schema (each argument's
        ``target_group`` names which ``character_view.target_groups`` entry holds the
        eligible entity ids). ``total_available`` reports how many matched before the
        ``limit``. Omit ``query`` to page the whole catalogue.

        ``mode`` is ``"substring"`` (default; matches anywhere) or ``"word"`` (matches only
        where a word -- split on hyphen, underscore, whitespace, and other punctuation --
        starts with the query, so ``"eat"`` will not match ``creature`` or ``defeat``).
        """

        try:
            return serialize_action_search(
                actor, query=query, limit=limit, mode=mode
            ).model_dump()
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def list_actions() -> dict[str, Any]:
        """Return the entire available action catalogue (every verb and its argument schema).

        This is large; prefer ``search_actions(query)`` for normal use. Useful when an agent
        wants the complete set of verbs at once.
        """

        return serialize_action_search(actor, query="", limit=0).model_dump()

    @mcp.tool()
    def examine(agent_id: str, entity_id: str | None = None) -> dict[str, Any]:
        """Inspect one entity the character can see or carry -- or itself.

        Returns the relevant component values on the entity (e.g. food nutrition/spoiled,
        a door's locked state, container open state). Omit ``entity_id`` (or pass the
        character's own id) to inspect yourself, which additionally returns your private
        needs/affect and human-readable status lines plus action/focus points. Examining
        another character never reveals their private needs -- only outwardly visible state.
        """

        try:
            character, _controller, _generation = _controlled_or_requested_character(
                actor, agent_id, None
            )
            return serialize_examine(
                actor,
                str(character),
                entity_id,
                fragment_providers=fragment_providers,
            ).model_dump()
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def room_view(room_id: str) -> dict[str, Any]:
        """Return a structured view of one room: entities, exits, and sprites."""

        try:
            return serialize_room_projection(actor, room_id).model_dump()
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def character_commands(
        agent_id: str, character_id: str | None = None
    ) -> dict[str, Any]:
        """Return the queued (not-yet-resolved) commands for the agent's character.

        Commands resolve on later world ticks, so this reflects what is still pending.
        """

        try:
            character, _controller, _generation = _controlled_or_requested_character(
                actor, agent_id, character_id
            )
            return serialize_character_queued_commands(actor, str(character)).model_dump()
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def component_schema(types: list[str] | None = None) -> dict[str, Any]:
        """Return JSON schemas for ECS component types, so an agent can learn what the

        components on perceived entities mean (e.g. ``FoodComponent``). Pass ``types`` to
        filter to specific component names; omit it for the full set with live usage counts.
        """

        schema = world_schema(actor)
        if types:
            wanted = set(types)
            components = {
                name: item for name, item in schema.components.items() if name in wanted
            }
        else:
            components = dict(schema.components)
        return {
            "ok": True,
            "world_epoch": schema.world_epoch,
            "components": {name: item.model_dump() for name, item in components.items()},
        }

    @mcp.tool()
    def perceived_events(
        agent_id: str, since: int | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Return recent events the agent's character caused or perceived in its room.

        Use this to observe outcomes of semi-turn-based commands: a queued command's
        execution or rejection (with reason) shows up here once it resolves. ``since`` is a
        watermark cursor; pass back the returned ``next_cursor`` to fetch only newer events.
        """

        return event_bridge.perceived_for_agent(agent_id, since=since, limit=limit)

    @mcp.tool()
    async def claim_character(
        agent_id: str,
        character_name: str | None = None,
        character_id: str | None = None,
        label: str = "",
        allow_child_claims: bool = False,
    ) -> dict[str, Any]:
        """Claim a suspended or named character for an MCP agent id."""

        try:
            async with actor._lock:
                claimed = assign_mcp_controller(
                    actor,
                    agent_id=agent_id,
                    character_name=character_name,
                    character_id=character_id,
                    label=label,
                    allow_child_claims=allow_child_claims,
                )
                await actor.bus.publish(
                    CharacterClaimedEvent(
                        **actor._event_base(
                            actor_id=claimed["character_id"],
                            character_id=claimed["character_id"],
                            controller_id=claimed["controller_id"],
                            generation=claimed["controller_generation"],
                        )
                    )
                )
                return claimed
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    async def release_character(
        agent_id: str,
        mode: str = "suspend",
        reason: str = "released by MCP client",
        model: str | None = None,
        provider: str = "ollama",
    ) -> dict[str, Any]:
        """Release an MCP-controlled character to suspended or LLM control."""

        try:
            async with actor._lock:
                return release_mcp_controller(
                    actor,
                    agent_id=agent_id,
                    mode=mode,
                    reason=reason,
                    model=model,
                    provider=provider,
                )
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    async def send_command(
        agent_id: str,
        command_type: str,
        payload: dict[str, Any] | None = None,
        character_id: str | None = None,
        cost_action: int = 1,
        cost_focus: int = 0,
        lane: str = "world",
        on_insufficient_points: str = "queue",
        expires_at_epoch: int | None = None,
    ) -> dict[str, Any]:
        """Queue a world command from an MCP-controlled character."""

        try:
            character, controller, generation = _controlled_or_requested_character(
                actor, agent_id, character_id
            )
            if command_type not in actor.available_command_types():
                raise ToolError(
                    f"unknown command_type {command_type!r}; call search_actions to find "
                    "valid verbs before sending"
                )
            command = build_submitted_command(
                character_id=str(character),
                controller_id=str(controller),
                controller_generation=generation,
                command_type=command_type,
                payload=payload or {},
                cost=CommandCost(action=cost_action, focus=cost_focus),
                lane=Lane(lane),
                on_insufficient_points=OnInsufficientPoints(on_insufficient_points),
                submitted_at_epoch=actor.epoch,
                expires_at_epoch=expires_at_epoch,
            )
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        await actor.submit(command)
        return {
            "ok": True,
            "queued": True,
            "command_id": command.command_id,
            "character_id": command.character_id,
            "command_type": command.command_type,
            "note": (
                "Queued only. Commands resolve on a later world tick and may still be "
                "rejected. Observe the outcome via perceived_events (execution or "
                "CommandRejectedEvent with a reason) or character_commands (still pending)."
            ),
        }

    @mcp.tool()
    async def patch_world_admin(
        admin_token: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply a world editor patch. Requires the MCP admin token."""

        admin(admin_token)
        try:
            response = await patch_world(
                WorldPatchRequest.model_validate({"operations": operations})
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @mcp.tool()
    async def generate_world_admin(
        admin_token: str,
        seed: str | None = None,
        generator: str | None = None,
        max_rooms: int | None = None,
        confirm_reset: bool = False,
        save: bool = False,
    ) -> dict[str, Any]:
        """Start replacing the world through an enabled generator. Requires admin token."""

        admin(admin_token)
        try:
            response = await generate_world(
                WorldGenerateRequest(
                    seed=seed,
                    generator=generator,
                    max_rooms=max_rooms,
                    confirm_reset=confirm_reset,
                    save=save,
                )
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @mcp.tool()
    async def world_generation_status_admin(admin_token: str) -> dict[str, Any]:
        """Return the current async world generation job status. Requires admin token."""

        admin(admin_token)
        return (await generation_status()).model_dump(mode="json")

    @mcp.tool()
    def generate_room_patch_admin(
        admin_token: str,
        door_entity_id: str,
        direction: str | None = None,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate a room patch behind a door. Requires admin token."""

        admin(admin_token)
        try:
            response = generate_room(
                WorldRoomGenerationRequest(
                    door_entity_id=door_entity_id,
                    direction=direction,
                    prompt=prompt,
                )
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @mcp.tool()
    def generate_character_patch_admin(
        admin_token: str,
        room_entity_id: str,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate a character patch for a room. Requires admin token."""

        admin(admin_token)
        try:
            response = generate_character(
                WorldCharacterGenerationRequest(room_entity_id=room_entity_id, prompt=prompt)
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @mcp.tool()
    def generate_item_patch_admin(
        admin_token: str,
        container_entity_id: str,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate an item patch for a room or container. Requires admin token."""

        admin(admin_token)
        try:
            response = generate_item(
                WorldItemGenerationRequest(
                    container_entity_id=container_entity_id,
                    prompt=prompt,
                )
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @mcp.tool()
    def generate_event_patch_admin(
        admin_token: str,
        room_entity_id: str,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate a story event patch for a room. Requires admin token."""

        admin(admin_token)
        try:
            response = generate_event(
                WorldEventGenerationRequest(room_entity_id=room_entity_id, prompt=prompt)
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    del worldgen_options
    mcp_app = mcp.streamable_http_app()
    session_manager = getattr(mcp, "session_manager", None)
    if session_manager is not None:
        mcp_app.bunnyland_mcp_session_manager = session_manager
    mcp_app.bunnyland_mcp_event_bridge = event_bridge
    return mcp_app


__all__ = [
    "ADMIN_TOKEN_ENV",
    "EVENTS_RESOURCE_URI",
    "MCP_MOUNT_PATH",
    "MCPEventBridge",
    "assign_mcp_controller",
    "create_bunnyland_mcp_app",
    "list_mcp_characters",
    "mcp_controlled_character",
    "mcp_enabled",
    "release_mcp_controller",
    "render_mcp_agent_prompt",
]
