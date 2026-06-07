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
from ..core.ecs import parse_entity_id
from ..core.events import DomainEvent
from ..mechanics.lifesim import LifeStageComponent
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
from ..server.serialization import event_message, serialize_world

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
CHILD_LIFE_STAGES = frozenset({"baby", "infant", "toddler", "child"})
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
    if not character.has_component(LifeStageComponent):
        return False
    stage = character.get_component(LifeStageComponent).stage
    return stage.lower() in CHILD_LIFE_STAGES


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
        lowered = character_name.lower()
        exact = [
            character
            for character in characters
            if character.get_component(IdentityComponent).name.lower() == lowered
        ]
        if exact:
            return exact[0]
        prefix = [
            character
            for character in characters
            if character.get_component(IdentityComponent).name.lower().startswith(lowered)
        ]
        if len(prefix) == 1:
            return prefix[0]
        if len(prefix) > 1:
            names = ", ".join(
                character.get_component(IdentityComponent).name for character in prefix
            )
            raise RuntimeError(f"multiple characters match {character_name!r}: {names}")
        names = ", ".join(
            character.get_component(IdentityComponent).name for character in characters
        )
        raise RuntimeError(
            f"no character named {character_name!r} exists in the world. "
            f"Available characters: {names}"
        )
    for character in characters:
        if character.has_component(SuspendedComponent) and (
            allow_child_claims or not _is_child_character(character)
        ):
            return character
    raise RuntimeError("no suspended claimable character exists in the world")


def _mcp_controller_for(actor: WorldActor, agent_id: str):
    controllers = actor.world.query().with_all([MCPControllerComponent])
    for entity in sorted(controllers.execute_entities(), key=lambda item: str(item.id)):
        if entity.get_component(MCPControllerComponent).agent_id == agent_id:
            return entity
    return None


def mcp_controlled_character(actor: WorldActor, agent_id: str):
    controller = _mcp_controller_for(actor, agent_id)
    if controller is None:
        return None
    for character in actor.world.query().with_all([CharacterComponent]).execute_entities():
        for edge, controller_id in character.get_relationships(ControlledBy):
            if controller_id == controller.id:
                return character.id, controller.id, edge.generation
    return None


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
) -> dict[str, Any]:
    found = mcp_controlled_character(actor, agent_id)
    if found is None:
        raise RuntimeError("agent is not controlling a character yet")
    character_id, _controller_id, generation = found
    builder = PromptBuilder(actor.world, fragment_providers=fragment_providers)
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
        )["prompt"]

    @mcp.tool()
    def list_characters() -> dict[str, Any]:
        """List claimable and controlled characters in the current world."""

        return {"ok": True, "characters": list_mcp_characters(actor)}

    @mcp.tool()
    def world_snapshot() -> dict[str, Any]:
        """Return the current serialized world snapshot."""

        return serialize_world(actor, meta)

    @mcp.tool()
    def runtime_status() -> dict[str, Any]:
        """Return current runtime status for the game loop."""

        return {
            "ok": True,
            "world_epoch": actor.epoch,
            "running": bool(loop.running) if loop is not None else False,
            "paused": bool(loop.paused) if loop is not None else False,
        }

    @mcp.tool()
    def agent_prompt(agent_id: str) -> dict[str, Any]:
        """Return the current Bunnyland prompt for an MCP-controlled agent."""

        try:
            return render_mcp_agent_prompt(
                actor,
                agent_id=agent_id,
                fragment_providers=fragment_providers,
            )
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

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
                return assign_mcp_controller(
                    actor,
                    agent_id=agent_id,
                    character_name=character_name,
                    character_id=character_id,
                    label=label,
                    allow_child_claims=allow_child_claims,
                )
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
