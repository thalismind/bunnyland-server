"""Streamable HTTP MCP server mounted into the existing FastAPI app."""

from __future__ import annotations

import functools
import inspect
import json
import os
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urlsplit

from pydantic import AnyUrl
from relics import EntityId

from .. import telemetry
from ..claims import (
    CLIENT_KIND_MCP,
    ClaimSecretRegistry,
    add_claim,
    claim_client_matches,
    claimable_characters,
    claimed_character_for,
    controlled_character,
    controller_claim,
    ensure_claim_secret,
    is_child_character,
    match_character_by_name,
    matching_controller,
    remove_claim,
    transfer_claim,
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
from ..core.world_actor import CONTROL_COMMANDS
from ..llm_agents.specs import BehaviorTreeSpec, ScriptSpec
from ..plugins.ids import MCP
from ..prompts import PromptBuilder, render_prompt
from ..server.admin import save_configured_world
from ..server.auth import WORLD_ADMIN_SCOPE, WORLD_PLAY_SCOPE, TokenPrincipal
from ..server.client_ids import (
    ADMIN_CLIENT_IDS_ENV,
    CLIENT_ID_HEADER,
    PLAYER_CLIENT_IDS_ENV,
    configured_client_id_allowlist,
    require_allowed_client_id,
)
from ..server.models import (
    CharacterChatRequest,
    ControllerAssignmentRequest,
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldGenerateRequest,
    WorldGenerationStatusResponse,
    WorldImageGenerationRequest,
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

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor
    from ..engine import GameLoop
    from ..persistence import WorldMeta
    from ..plugins.model import Plugin
    from ..server.models import (
        ControllerDefinitionListResponse,
        WorldCharacterGenerationResponse,
        WorldEventGenerationResponse,
        WorldGenerateResponse,
        WorldImageGenerationResponse,
        WorldItemGenerationResponse,
        WorldPatchResponse,
        WorldRoomGenerationResponse,
    )
    from ..worldgen import GenOptions


def _now_unix() -> int:
    from time import time

    return int(time())


MCP_MOUNT_PATH = "/v1/mcp"
EVENTS_RESOURCE_URI = "bunnyland://events/recent"
_DEFAULT_CLAIM_SECRETS = ClaimSecretRegistry()


def mcp_enabled(plugins: Sequence[Plugin] | None) -> bool:
    return any(plugin.id == MCP or plugin.id.endswith(".mcp") for plugin in plugins or ())


def _traced_tool(fn):
    """Wrap an MCP tool handler in an ``mcp.<tool>`` span.

    ``functools.wraps`` keeps the original signature (via ``__wrapped__``) so FastMCP still
    introspects the tool's parameters for its JSON schema. No-op when telemetry is disabled.
    """
    name = f"mcp.{fn.__name__}"
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            with telemetry.span(name) as span:
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    telemetry.mark_span_error(str(exc), span)
                    raise
                telemetry.mark_span_ok(span)
                return result

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with telemetry.span(name) as span:
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                span.record_exception(exc)
                telemetry.mark_span_error(str(exc), span)
                raise
            telemetry.mark_span_ok(span)
            return result

    return wrapper


def _client_events_uri(client_id: str) -> str:
    return f"bunnyland://clients/{quote(client_id, safe='')}/events"


def _client_prompt_uri(client_id: str) -> str:
    return f"bunnyland://clients/{quote(client_id, safe='')}/prompt"


def _client_id_from_uri(uri: str, suffix: str) -> str | None:
    prefix = "bunnyland://clients/"
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

    def recent_for_client(self, client_id: str) -> list[dict[str, Any]]:
        controlled = mcp_controlled_character(self.actor, client_id)
        if controlled is None:
            return []
        character_id = str(controlled[0])
        filtered: list[dict[str, Any]] = []
        for message in self._recent:
            event = message.get("data", {}).get("event", {})
            if event.get("actor_id") == character_id:
                filtered.append(message)
        return filtered

    def perceived_for_client(
        self, client_id: str, *, since: int | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Return recent events the client's character caused or perceived in its room.

        ``since`` is a watermark cursor: only events recorded after it are returned. The
        response carries ``next_cursor`` to pass as ``since`` on the next poll so streaming
        gaps and missed notifications can be reconciled.
        """

        controlled = mcp_controlled_character(self.actor, client_id)
        if controlled is None:
            return {"ok": False, "client_id": client_id, "events": [], "next_cursor": since or 0}
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
            "client_id": client_id,
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
        message = event_message(event, self.actor.plugins)
        self._seq += 1
        message["seq"] = self._seq
        self._recent.append(message)
        await self._notify_changed_resources(message)

    async def _notify_changed_resources(self, message: dict[str, Any]) -> None:
        event = message.get("data", {}).get("event", {})
        event_actor_id = event.get("actor_id")
        uris: set[str] = {EVENTS_RESOURCE_URI}

        for uri in self._subscriptions:
            if _client_id_from_uri(uri, "/prompt") is not None:
                # Prompt context can change for indirect reasons: room events, nearby
                # actors, conditions, and point regeneration can all alter prompt text.
                uris.add(uri)
                continue
            client_id = _client_id_from_uri(uri, "/events")
            if client_id is None:
                continue
            controlled = mcp_controlled_character(self.actor, client_id)
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
    claimable = claimable_characters(
        actor,
        characters,
        allow_child_claims=allow_child_claims,
    )
    if claimable:
        return claimable[0]
    raise RuntimeError("no suspended claimable character exists in the world")


def _mcp_controller_for(actor: WorldActor, client_id: str):
    return matching_controller(
        actor,
        MCPControllerComponent,
        lambda controller: controller.client_id == client_id,
    )


def mcp_controlled_character(actor: WorldActor, client_id: str):
    return controlled_character(
        actor,
        MCPControllerComponent,
        lambda controller: controller.client_id == client_id,
    )


def assign_mcp_controller(
    actor: WorldActor,
    *,
    claim_secrets: ClaimSecretRegistry | None = None,
    client_id: str,
    claim_id: str | None = None,
    claim_secret: str | None = None,
    character_name: str | None = None,
    character_id: str | None = None,
    label: str = "",
    allow_child_claims: bool = False,
) -> dict[str, Any]:
    """Assign an MCP controller to a named/id character, or the first suspended one."""

    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    client_id = client_id.strip()
    if not client_id:
        raise RuntimeError("client_id is required")
    character = _match_character(
        actor,
        character_name,
        character_id,
        allow_child_claims=allow_child_claims,
    )
    if _is_child_character(character) and not allow_child_claims:
        name = character.get_component(IdentityComponent).name
        raise RuntimeError(f"{name} is a child character and cannot be claimed on this server")

    active_controller = None
    for _edge, controller_id in character.get_relationships(ControlledBy):
        if actor.world.has_entity(controller_id):
            active_controller = actor.world.get_entity(controller_id)
            break
    active_claim = controller_claim(active_controller) if active_controller is not None else None
    issued_claim_id = None
    validated_claim_secret = False
    if active_claim is not None:
        if not claim_client_matches(active_claim, client_id):
            raise RuntimeError("character is already claimed")
        try:
            ensure_claim_secret(
                claim_secrets,
                active_claim,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
        except PermissionError as exc:
            raise RuntimeError(str(exc)) from exc
        validated_claim_secret = True
        issued_claim_id = active_claim.claim_id
        claim_secret = claim_secrets.secret(active_claim.claim_id)

    controller = _mcp_controller_for(actor, client_id)
    if controller is not None:
        existing_claim = controller_claim(controller)
        if existing_claim is not None and existing_claim.character_id != str(character.id):
            controller = None
    if controller is None:
        controller = spawn_entity(
            actor.world,
            [MCPControllerComponent(client_id=client_id, label=label.strip())],
        )
    if active_claim is not None and active_controller is not None:
        transfer_claim(active_controller, controller)
    claim = add_claim(
        controller,
        client_kind=CLIENT_KIND_MCP,
        client_id=client_id,
        character_id=str(character.id),
        label=label,
        claim_id=issued_claim_id,
        now_unix=_now_unix(),
    )
    if (
        not validated_claim_secret
        or claim_secret is None
        or not claim_secrets.has_secret(claim.claim_id)
    ):
        claim_secret = claim_secrets.issue(claim.claim_id)

    generation = actor.assign_controller(character.id, controller.id)
    if character.has_component(SuspendedComponent):
        character.remove_component(SuspendedComponent)
    identity = character.get_component(IdentityComponent)
    return {
        "ok": True,
        "client_id": client_id,
        "character_id": str(character.id),
        "character_name": identity.name,
        "controller_id": str(controller.id),
        "controller_generation": generation,
        "claim_id": claim.claim_id,
        "claim_secret": claim_secret,
    }


def release_mcp_controller(
    actor: WorldActor,
    *,
    claim_secrets: ClaimSecretRegistry | None = None,
    client_id: str,
    claim_id: str | None = None,
    claim_secret: str | None = None,
    fallback_controller: str = "suspend",
    reason: str = "released by MCP client",
    model: str | None = None,
    provider: str = "ollama",
) -> dict[str, Any]:
    """Release active control to another controller while retaining the claim."""

    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    found = mcp_controlled_character(actor, client_id)
    if found is None:
        raise RuntimeError("client is not controlling a character yet")
    character_id, old_controller_id, _generation = found
    character = actor.world.get_entity(character_id)
    identity = character.get_component(IdentityComponent)
    old_controller = actor.world.get_entity(old_controller_id)
    claim = controller_claim(old_controller)
    if claim is None or not claim_client_matches(claim, client_id):
        raise RuntimeError("client does not hold the claim for this character")
    try:
        ensure_claim_secret(
            claim_secrets,
            claim,
            claim_id=claim_id,
            claim_secret=claim_secret,
        )
    except PermissionError as exc:
        raise RuntimeError(str(exc)) from exc

    fallback = fallback_controller.strip() or "suspend"
    parsed = parse_entity_id(fallback)
    if parsed is not None and actor.world.has_entity(parsed):
        controller = actor.world.get_entity(parsed)
        controller_kind = actor._controller_kind(parsed)
        if controller_kind == "unknown":
            raise RuntimeError("fallback_controller is not a controller")
        existing_claim = controller_claim(controller)
        if existing_claim is not None and existing_claim.claim_id != claim.claim_id:
            raise RuntimeError("fallback controller is already claimed")
        generation = (
            actor.suspend(character.id, controller.id, reason=reason)
            if controller_kind == "suspended"
            else actor.assign_controller(character.id, controller.id)
        )
        if controller_kind != "suspended" and character.has_component(SuspendedComponent):
            character.remove_component(SuspendedComponent)
    elif fallback in {"suspend", "suspended", "offline"}:
        controller = spawn_entity(actor.world, [SuspendedControllerComponent(reason=reason)])
        generation = actor.suspend(character.id, controller.id, reason=reason)
        controller_kind = "suspended"
    elif fallback in {"llm", "ai"}:
        controller = spawn_entity(
            actor.world,
            [
                LLMControllerComponent(
                    profile_name="default",
                    model=model or os.environ.get("BUNNYLAND_CHARACTER_MODEL", "deepseek-v4-flash"),
                    provider=provider,
                )
            ],
        )
        generation = actor.assign_controller(character.id, controller.id)
        if character.has_component(SuspendedComponent):
            character.remove_component(SuspendedComponent)
        controller_kind = "llm"
    else:
        raise RuntimeError("fallback_controller is not a controller")

    transfer_claim(old_controller, controller)
    return {
        "ok": True,
        "client_id": client_id,
        "character_id": str(character.id),
        "character_name": identity.name,
        "controller_id": str(controller.id),
        "controller_generation": generation,
        "controller_kind": controller_kind,
        "claim_id": claim.claim_id,
        "claim_secret": claim_secrets.secret(claim.claim_id) or "",
    }


def release_mcp_claim(
    actor: WorldActor,
    *,
    claim_secrets: ClaimSecretRegistry | None = None,
    client_id: str,
    claim_id: str | None = None,
    claim_secret: str | None = None,
) -> dict[str, Any]:
    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    found = claimed_character_for(
        actor,
        client_id=client_id,
    )
    if found is None:
        raise RuntimeError("client is not controlling a character yet")
    character, controller, _edge, claim = found
    try:
        ensure_claim_secret(
            claim_secrets,
            claim,
            claim_id=claim_id,
            claim_secret=claim_secret,
        )
    except PermissionError as exc:
        raise RuntimeError(str(exc)) from exc
    remove_claim(controller, claim_secrets)
    return {
        "ok": True,
        "client_id": client_id,
        "character_id": str(character.id),
        "controller_id": str(controller.id),
        "claim_id": claim.claim_id,
    }


async def render_mcp_client_prompt(
    actor: WorldActor,
    *,
    claim_secrets: ClaimSecretRegistry | None = None,
    client_id: str,
    claim_id: str | None = None,
    claim_secret: str | None = None,
    fragment_providers: Sequence[Any] = (),
    persona_providers: Sequence[Any] = (),
    prompt_filter_runtime=None,
) -> dict[str, Any]:
    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    character_id, _controller_id, generation = _controlled_or_requested_character(
        actor,
        claim_secrets,
        client_id,
        None,
        claim_id=claim_id,
        claim_secret=claim_secret,
    )
    builder = PromptBuilder(
        actor.world,
        fragment_providers=fragment_providers,
        persona_providers=persona_providers,
        include_entity_ids=True,
    )
    context = builder.build(character_id, epoch=actor.epoch)
    from ..prompts.filters import PromptFilterRuntime, apply_prompt_filters

    runtime = prompt_filter_runtime or getattr(actor, "prompt_filter_runtime", None)
    if runtime is None:
        runtime = PromptFilterRuntime.from_actor(actor)
    prompt = await apply_prompt_filters(
        render_prompt(context),
        runtime=runtime,
        character=actor.world.get_entity(character_id),
        context=context,
        epoch=actor.epoch,
    )
    return {
        "ok": True,
        "client_id": client_id,
        "character_id": str(character_id),
        "controller_generation": generation,
        "world_epoch": actor.epoch,
        "prompt": prompt,
    }


def _controlled_or_requested_character(
    actor: WorldActor,
    claim_secrets: ClaimSecretRegistry | None,
    client_id: str,
    character_id: str | None,
    *,
    claim_id: str | None = None,
    claim_secret: str | None = None,
) -> tuple[EntityId, EntityId, int]:
    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    found = claimed_character_for(
        actor,
        client_id=client_id,
    )
    if found is None:
        raise RuntimeError("client is not controlling a character yet")
    character, controller, edge, claim = found
    try:
        ensure_claim_secret(
            claim_secrets,
            claim,
            claim_id=claim_id,
            claim_secret=claim_secret,
        )
    except PermissionError as exc:
        raise RuntimeError(str(exc)) from exc

    if character_id is None:
        return character.id, controller.id, edge.generation

    requested_id = parse_entity_id(character_id)
    if requested_id is None or not actor.world.has_entity(requested_id):
        raise RuntimeError(f"character {character_id!r} does not exist")
    if character.id != requested_id:
        raise RuntimeError("client does not control the requested character")
    return character.id, controller.id, edge.generation


def create_bunnyland_mcp_app(
    *,
    actor: WorldActor,
    meta: WorldMeta,
    loop: GameLoop | None,
    player_client_ids: str | Sequence[str] | None = None,
    admin_client_ids: str | Sequence[str] | None = None,
    save_path: str | Path | None = None,
    patch_world: Callable[[WorldPatchRequest], Awaitable[WorldPatchResponse]],
    generate_world: Callable[[WorldGenerateRequest], Awaitable[WorldGenerateResponse]],
    generation_status: Callable[[], Awaitable[WorldGenerationStatusResponse]],
    generate_room: Callable[[WorldRoomGenerationRequest], Awaitable[WorldRoomGenerationResponse]],
    generate_character: Callable[
        [WorldCharacterGenerationRequest], Awaitable[WorldCharacterGenerationResponse]
    ],
    generate_item: Callable[[WorldItemGenerationRequest], Awaitable[WorldItemGenerationResponse]],
    generate_event: Callable[
        [WorldEventGenerationRequest], Awaitable[WorldEventGenerationResponse]
    ],
    generate_image: Callable[[WorldImageGenerationRequest], Awaitable[WorldImageGenerationResponse]]
    | None = None,
    scene_image: Callable[[str], Awaitable[WorldImageGenerationResponse | None]] | None = None,
    chat: Callable[
        [str, CharacterChatRequest, str | None], Awaitable[dict[str, Any]]
    ]
    | None = None,
    assign_controller: Callable[[ControllerAssignmentRequest], Awaitable[WorldPatchResponse]]
    | None = None,
    list_generators: Callable[[], dict[str, Any]] | None = None,
    register_script: Callable[[ScriptSpec], Awaitable[ControllerDefinitionListResponse]]
    | None = None,
    register_behavior: Callable[[BehaviorTreeSpec], Awaitable[ControllerDefinitionListResponse]]
    | None = None,
    list_controller_definitions: Callable[[], ControllerDefinitionListResponse] | None = None,
    fragment_providers: Sequence[Any] = (),
    persona_providers: Sequence[Any] = (),
    worldgen_options: GenOptions | None = None,
    claim_secrets: ClaimSecretRegistry | None = None,
    plugins: Sequence[Plugin] = (),
    trusted_origins: Sequence[str] = (),
):
    """Create the ASGI MCP app.

    Importing the SDK here keeps the ``mcp`` extra optional for normal Bunnyland installs.
    """

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.server.fastmcp.exceptions import ToolError
    except ImportError as exc:
        raise RuntimeError(
            "the MCP server requires the 'mcp' extra: pip install bunnyland[mcp]"
        ) from exc

    transport_security = None
    if trusted_origins:
        from mcp.server.transport_security import TransportSecuritySettings

        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(
                dict.fromkeys(urlsplit(origin).netloc for origin in trusted_origins)
            ),
            allowed_origins=list(dict.fromkeys(trusted_origins)),
        )

    mcp = FastMCP(
        "Bunnyland",
        instructions=(
            "Control a Bunnyland character, inspect the world, and perform "
            "admin-authorized world patching or generation."
        ),
        stateless_http=False,
        json_response=True,
        streamable_http_path="/",
        transport_security=transport_security,
    )
    event_bridge = MCPEventBridge(actor)
    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    allowed_player_client_ids = configured_client_id_allowlist(
        player_client_ids, PLAYER_CLIENT_IDS_ENV
    )
    allowed_admin_client_ids = configured_client_id_allowlist(
        admin_client_ids, ADMIN_CLIENT_IDS_ENV
    )

    def _next_tick_epoch() -> int | None:
        """Estimated world epoch a freshly-queued command resolves at (the next tick).

        Queued commands are dispatched on the following tick, which advances the world
        clock by ``tick_seconds * time_scale``. Returns None when no loop is attached or a
        command is deferred for insufficient points -- it is the earliest expected epoch.
        """

        tick = getattr(loop, "tick_seconds", None)
        scale = getattr(loop, "time_scale", None)
        if tick is None or scale is None:
            return None
        return actor.epoch + int(round(float(tick) * float(scale)))

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

    def _request():
        try:
            return mcp.get_context().request_context.request
        except (LookupError, AttributeError, ValueError):
            return None

    def _request_auth() -> tuple[TokenPrincipal | None, Any | None]:
        request = _request()
        if request is None:
            return None, None
        principal = getattr(getattr(request, "state", None), "auth_principal", None)
        return (principal if isinstance(principal, TokenPrincipal) else None), request

    def _request_claim_header(name: str) -> str | None:
        headers = getattr(_request(), "headers", {}) or {}
        return headers.get(name)

    def _require_request_scopes(required_scopes: tuple[str, ...]) -> None:
        principal, request = _request_auth()
        if request is None or principal is None:
            raise ToolError("authenticated MCP request context required")
        missing = [scope for scope in required_scopes if scope not in principal.scopes]
        if missing:
            raise ToolError(f"{', '.join(missing)} scope required")
        if WORLD_ADMIN_SCOPE in required_scopes:
            headers = getattr(request, "headers", {}) or {}
            try:
                require_allowed_client_id(
                    headers.get(CLIENT_ID_HEADER), allowed_admin_client_ids, "admin"
                )
            except PermissionError as exc:
                raise ToolError(str(exc)) from exc

    def _authorized_capability(required_scopes: tuple[str, ...], fn):
        if not required_scopes or any(
            scope not in {WORLD_PLAY_SCOPE, WORLD_ADMIN_SCOPE} for scope in required_scopes
        ):
            raise ValueError("MCP capabilities require an explicit play/admin access policy")
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                _require_request_scopes(required_scopes)
                return await fn(*args, **kwargs)

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _require_request_scopes(required_scopes)
            return fn(*args, **kwargs)

        return wrapper

    def _tool(required_scopes: tuple[str, ...]):
        def register(fn):
            return mcp.tool()(_authorized_capability(required_scopes, fn))

        return register

    def _resource(*args, required_scopes: tuple[str, ...], **kwargs):
        def register(fn):
            return mcp.resource(*args, **kwargs)(
                _authorized_capability(required_scopes, fn)
            )

        return register

    def _prompt(*args, required_scopes: tuple[str, ...], **kwargs):
        def register(fn):
            authorized = _authorized_capability(required_scopes, fn)
            prompt_registrar = getattr(mcp, "prompt", None)
            if prompt_registrar is None:
                return authorized
            return prompt_registrar(*args, **kwargs)(authorized)

        return register

    play_tool = _tool((WORLD_PLAY_SCOPE,))
    admin_tool = _tool((WORLD_ADMIN_SCOPE,))

    def play_resource(*args, **kwargs):
        return _resource(*args, required_scopes=(WORLD_PLAY_SCOPE,), **kwargs)

    def admin_resource(*args, **kwargs):
        return _resource(*args, required_scopes=(WORLD_ADMIN_SCOPE,), **kwargs)

    def play_prompt(*args, **kwargs):
        return _prompt(*args, required_scopes=(WORLD_PLAY_SCOPE,), **kwargs)

    class PolicyRegistrar:
        """Capability registrar that makes an access policy mandatory at the call site."""

        def __init__(self, plugin_id: str) -> None:
            self.plugin_id = plugin_id
            self.prefix = "".join(
                character if character.isalnum() else "_" for character in plugin_id
            )

        def _name(self, name: str) -> str:
            return f"{self.prefix}__{name}"

        def tool(self, *, scopes: Sequence[str]):
            def register(fn):
                authorized = _authorized_capability(tuple(scopes), fn)
                authorized.__name__ = self._name(fn.__name__)
                return mcp.tool()(authorized)

            return register

        def resource(self, uri: str, *, scopes: Sequence[str], **kwargs):
            namespaced_uri = (
                f"bunnyland://v1/extensions/{quote(self.plugin_id, safe='')}/"
                f"{quote(uri, safe='')}"
            )
            if "name" in kwargs:
                kwargs["name"] = self._name(str(kwargs["name"]))
            return _resource(
                namespaced_uri,
                required_scopes=tuple(scopes),
                **kwargs,
            )

        def prompt(self, *args, scopes: Sequence[str], **kwargs):
            def register(fn):
                authorized = _authorized_capability(tuple(scopes), fn)
                authorized.__name__ = self._name(fn.__name__)
                if "name" in kwargs:
                    kwargs["name"] = self._name(str(kwargs["name"]))
                return mcp.prompt(*args, **kwargs)(authorized)

            return register

    def admin() -> None:
        _require_request_scopes((WORLD_ADMIN_SCOPE,))

    def player(client_id: str | None) -> str | None:
        _require_request_scopes((WORLD_PLAY_SCOPE,))
        request_client_id = _request_claim_header(CLIENT_ID_HEADER)
        if request_client_id and client_id and request_client_id != client_id:
            raise ToolError("client_id must match the authenticated request header")
        client_id = request_client_id or client_id
        try:
            return require_allowed_client_id(client_id, allowed_player_client_ids, "player")
        except PermissionError as exc:
            raise ToolError(str(exc)) from exc

    def request_claim_secret(provided: str | None) -> str | None:
        header_secret = _request_claim_header("X-Bunnyland-Claim-Secret")
        if provided and provided != header_secret:
            if _request_claim_header(CLIENT_ID_HEADER):
                raise ToolError("claim secret must be supplied in X-Bunnyland-Claim-Secret")
            return provided
        return header_secret

    def controlled_or_requested_player(
        client_id: str,
        character_id: str | None,
        *,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> tuple[EntityId, EntityId, int]:
        player(client_id)
        claim_secret = request_claim_secret(claim_secret)
        return _controlled_or_requested_character(
            actor,
            claim_secrets,
            client_id,
            character_id,
            claim_id=claim_id,
            claim_secret=claim_secret,
        )

    def recent_world_events_resource() -> str:
        return json.dumps({"ok": True, "events": event_bridge.recent_messages()})

    def client_events_resource(client_id: str) -> str:
        player(client_id)
        found = claimed_character_for(
            actor,
            client_id=client_id,
        )
        if found is None:
            raise RuntimeError("client is not controlling a character yet")
        try:
            ensure_claim_secret(
                claim_secrets,
                found[3],
                claim_id=_request_claim_header("X-Bunnyland-Claim-Id"),
                claim_secret=_request_claim_header("X-Bunnyland-Claim-Secret"),
            )
        except PermissionError as exc:
            raise RuntimeError(str(exc)) from exc
        return json.dumps(
            {
                "ok": True,
                "client_id": client_id,
                "events": event_bridge.recent_for_client(client_id),
            }
        )

    async def client_prompt_resource(client_id: str) -> str:
        player(client_id)
        return (
            await render_mcp_client_prompt(
                actor,
                claim_secrets=claim_secrets,
                client_id=client_id,
                claim_id=_request_claim_header("X-Bunnyland-Claim-Id"),
                claim_secret=_request_claim_header("X-Bunnyland-Claim-Secret"),
                fragment_providers=fragment_providers,
                persona_providers=persona_providers,
            )
        )["prompt"]

    @play_resource(
        "bunnyland://v1/features",
        name="features",
        description="Enabled Bunnyland interface capabilities.",
        mime_type="application/json",
    )
    def features_resource() -> str:
        return json.dumps(
            {
                "mcp": True,
                "character_chat": chat is not None,
                "image_generation": scene_image is not None,
            }
        )

    @play_resource(
        "bunnyland://v1/catalog",
        name="catalog",
        description="Component schemas, registered perspective queries, and play actions.",
        mime_type="application/json",
    )
    def catalog_resource() -> str:
        schema = world_schema(actor)
        return json.dumps(
            {
                "world_id": str(actor.world_id),
                "world_epoch": actor.epoch,
                "components": {
                    name: item.model_dump(mode="json")
                    for name, item in schema.components.items()
                },
                "edges": {
                    name: item.model_dump(mode="json") for name, item in schema.edges.items()
                },
                "queries": [
                    definition.name for definition in actor.perspective_queries.definitions()
                ],
                "actions": serialize_action_search(actor, query="", limit=0)
                .model_dump(mode="json")
                .get("actions", []),
            }
        )

    @play_resource(
        "bunnyland://v1/characters",
        name="character_lobby",
        description="Claimable and currently controlled character lobby.",
        mime_type="application/json",
    )
    def character_lobby_resource() -> str:
        return json.dumps(
            {
                "world_id": str(actor.world_id),
                "world_epoch": actor.epoch,
                "characters": list_mcp_characters(actor),
            }
        )

    @admin_resource(
        "bunnyland://v1/admin/world",
        name="admin_world",
        description="Administrative world overview.",
        mime_type="application/json",
    )
    def admin_world_resource() -> str:
        return json.dumps(serialize_world_overview(actor).model_dump(mode="json"))

    @admin_resource(
        "bunnyland://v1/admin/runtime",
        name="admin_runtime",
        description="Administrative world runtime state.",
        mime_type="application/json",
    )
    def admin_runtime_resource() -> str:
        return json.dumps(admin_runtime_status())

    @admin_resource(
        "bunnyland://v1/admin/generators",
        name="admin_generators",
        description="Registered world generators.",
        mime_type="application/json",
    )
    def admin_generators_resource() -> str:
        return json.dumps(list_generators() if list_generators is not None else {"generators": []})

    @admin_resource(
        "bunnyland://v1/admin/controller-definitions",
        name="admin_controller_definitions",
        description="Registered controller definitions and authoring libraries.",
        mime_type="application/json",
    )
    def admin_controller_definitions_resource() -> str:
        if list_controller_definitions is None:
            return json.dumps({"scripts": [], "behaviors": []})
        return json.dumps(list_controller_definitions().model_dump(mode="json"))

    @admin_resource(
        "bunnyland://v1/admin/generation-jobs/current",
        name="admin_generation_job",
        description="Current world-generation job state.",
        mime_type="application/json",
    )
    async def admin_generation_job_resource() -> str:
        return json.dumps((await generation_status()).model_dump(mode="json"))

    @play_prompt(
        name="play_bunnyland",
        description="Explain the normal claim, look, action, command, and observation loop.",
    )
    def play_bunnyland_prompt() -> str:
        return (
            "List and claim a character, then call play_look. Use play_search_actions and "
            "play_action_help before play_send_command. Observe results with "
            "play_recent_events or play_what_changed; release control or the claim when done."
        )

    @play_tool
    def play_list_characters() -> dict[str, Any]:
        """List claimable and controlled characters in the current world."""

        return {"ok": True, "characters": list_mcp_characters(actor)}

    @admin_tool
    @_traced_tool
    def admin_world_snapshot() -> dict[str, Any]:
        """Return the full raw ECS world snapshot (large; admin/debug and persistence).

        This is the heavy dump of every entity and component, so it is admin-only: seeing
        the whole world at once would be cheating. For normal use prefer the scoped
        projections: ``play_get_projection``/``play_look`` for a play-facing slice and
        ``admin_world_overview`` for the room-network map.
        """

        admin()
        return serialize_world(actor, meta)

    @admin_tool
    @_traced_tool
    def admin_world_overview() -> dict[str, Any]:
        """Return a slim, admin-only map of the whole room network (admin scope required).

        Rooms with ids, titles, exits, and occupant/item counts -- the privileged graph the
        admin and web graph clients render. Withheld from players: seeing the full map would
        be cheating. For a player's own view use ``character_view`` (their perceived room).
        """

        admin()
        return serialize_world_overview(actor).model_dump()

    @admin_tool
    @_traced_tool
    async def admin_save_world() -> dict[str, Any]:
        """Save the current world to the configured persistent JSON/YAML file.

        Requires an authenticated MCP request with world:admin scope. The server needs a save path
        (the same configuration used by the REST ``/admin/world/save`` endpoint).
        """

        admin()
        if save_path is None:
            raise ToolError("server was not started with --save")
        try:
            async with actor._lock:
                response = save_configured_world(actor, save_path, meta=meta)
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    def admin_runtime_status() -> dict[str, Any]:
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

    @admin_tool
    async def admin_pause_world() -> dict[str, Any]:
        """Pause the attached world runtime and return its new state."""

        if loop is None:
            raise ToolError("server runtime is not attached")
        publish = loop.pause()
        if publish is not None:
            await publish
        return admin_runtime_status()

    @admin_tool
    async def admin_resume_world() -> dict[str, Any]:
        """Resume the attached world runtime and return its new state."""

        if loop is None:
            raise ToolError("server runtime is not attached")
        publish = loop.resume()
        if publish is not None:
            await publish
        return admin_runtime_status()

    @_traced_tool
    async def _client_prompt_tool(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Return the current Bunnyland prompt for an MCP-controlled client."""

        try:
            player(client_id)
            return await render_mcp_client_prompt(
                actor,
                claim_secrets=claim_secrets,
                client_id=client_id,
                claim_id=claim_id,
                claim_secret=claim_secret,
                fragment_providers=fragment_providers,
                persona_providers=persona_providers,
            )
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    @_traced_tool
    def play_get_projection(
        client_id: str,
        character_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Return a structured, play-facing view for the client's character.

        This returns machine-readable room and character state, inventory, action/focus
        points, and ``target_groups`` resolving every targetable entity id. The full action
        catalogue is omitted here to keep the view small (progressive disclosure); use
        ``play_search_actions`` to find a verb and its argument schema, then read each
        argument's entity id from ``target_groups[argument.target_group]`` and call
        ``play_send_command``.
        """

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                character_id,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            data = serialize_character_projection(actor, str(character)).model_dump()
            actions = data.pop("actions", [])
            data["action_count"] = len(actions)
            data["actions_hint"] = (
                "Action catalogue omitted; call play_search_actions(query), "
                "then resolve ids from target_groups."
            )
            return data
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    @_traced_tool
    def play_look(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Summarize the controlled character's immediate situation and useful next steps."""

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                None,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            projection = serialize_character_projection(actor, str(character))
            available = [action for action in projection.actions if action.available]
            return {
                "summary": (
                    f"{projection.character_name} is in "
                    f"{projection.room.title or 'an unknown place'} with "
                    f"{len(projection.room.entities)} visible entities."
                ),
                "world_epoch": projection.world_epoch,
                "character_id": projection.character_id,
                "room": projection.room.model_dump(mode="json"),
                "points": projection.points.model_dump(mode="json"),
                "suggested_actions": [action.command_type for action in available[:8]],
                "next_actions": [
                    "Call play_examine for an interesting visible entity.",
                    "Call play_search_actions, then play_action_help before acting.",
                ],
            }
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    @_traced_tool
    def play_query_world(
        client_id: str,
        query: str,
        arguments: dict[str, Any] | None = None,
        character_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Run one bounded perspective query as the client's controlled character.

        The available names come from the enabled plugins' perspective-query registry.
        Results use the same claim-scoped projections as REST and never expose unrestricted
        Relics state.
        """

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                character_id,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            return actor.perspective_queries.execute(
                actor,
                query,
                arguments or {},
                actor_id=str(character),
                access="claim",
            ).model_dump(mode="json")
        except (PermissionError, RuntimeError, ValueError, TimeoutError) as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    def play_search_actions(
        query: str = "", limit: int = 30, mode: str = "substring"
    ) -> dict[str, Any]:
        """Search the action catalogue -- the MCP equivalent of the clients' action box.

        Matches ``query`` against each action's command_type, title, and tool name,
        returning a slim, paged list of actions with their argument schema (each argument's
        ``target_group`` names which ``character_view.target_groups`` entry holds the
        eligible entity ids). ``total_available`` reports how many matched before the
        ``limit``. Omit ``query`` to page the whole catalogue.

        ``mode`` is ``"substring"`` (default; matches anywhere), ``"word"`` (matches only
        where a word -- split on hyphen, underscore, whitespace, and other punctuation --
        starts with the query, so ``"eat"`` will not match ``creature`` or ``defeat``), or
        ``"smart"`` (uses a Chroma collection to rank the most relevant verbs).
        """

        try:
            return serialize_action_search(actor, query=query, limit=limit, mode=mode).model_dump()
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    def play_action_help(
        client_id: str,
        action: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Explain one action's availability, targets, requirements, cost, and blockers."""

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                None,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            projection = serialize_character_projection(actor, str(character))
            selected = next(
                (
                    candidate
                    for candidate in projection.actions
                    if action in {candidate.command_type, candidate.tool_name}
                ),
                None,
            )
            if selected is None:
                raise ToolError(
                    f"unknown action {action!r}; call play_search_actions to find one"
                )
            targets = {
                argument.key: [
                    target.model_dump(mode="json")
                    for target in projection.target_groups.get(argument.target_group or "", [])
                ]
                for argument in selected.arguments
                if argument.target_group
            }
            return {
                "summary": (
                    f"{selected.title} is "
                    f"{'available' if selected.available else 'not currently available'}."
                ),
                "action": selected.model_dump(mode="json"),
                "valid_targets": targets,
                "requirements": {
                    "meets_requirements": selected.meets_requirements,
                    "has_required_target": selected.has_required_target,
                },
                "cost": selected.cost.model_dump(mode="json"),
                "why_not": selected.unavailable_reason or None,
                "next_actions": (
                    ["Call play_send_command with this command_type and a valid target."]
                    if selected.available
                    else ["Address why_not, then call play_action_help again."]
                ),
            }
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    def _list_actions_legacy() -> dict[str, Any]:
        """Return the entire available action catalogue (every verb and its argument schema).

        This is large; prefer ``search_actions(query)`` for normal use. Useful when a client
        wants the complete set of verbs at once.
        """

        return serialize_action_search(actor, query="", limit=0).model_dump()

    @play_tool
    @_traced_tool
    def play_examine(
        client_id: str,
        entity_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Inspect one entity the character can see or carry -- or itself.

        Returns the relevant component values on the entity (e.g. food nutrition/spoiled,
        a door's locked state, container open state). Omit ``entity_id`` (or pass the
        character's own id) to inspect yourself, which additionally returns your private
        needs/affect and human-readable status lines plus action/focus points. Examining
        another character never reveals their private needs -- only outwardly visible state.
        """

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                None,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            return serialize_examine(
                actor,
                str(character),
                entity_id,
                fragment_providers=fragment_providers,
            ).model_dump()
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @_traced_tool
    def _room_view_legacy(room_id: str) -> dict[str, Any]:
        """Return a structured view of one room: entities, exits, and sprites."""

        try:
            return serialize_room_projection(actor, room_id).model_dump()
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    def play_pending_commands(
        client_id: str,
        character_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Return the queued (not-yet-resolved) commands for the client's character.

        Commands resolve on later world ticks, so this reflects what is still pending.
        """

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                character_id,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            data = serialize_character_queued_commands(actor, str(character)).model_dump()
            resolves_at_epoch = _next_tick_epoch()
            for queued in data["commands"]:
                queued["resolves_at_epoch"] = resolves_at_epoch
            return data
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    def _component_schema_legacy(types: list[str] | None = None) -> dict[str, Any]:
        """Return JSON schemas for ECS component types, so a client can learn what the

        components on perceived entities mean (e.g. ``FoodComponent``). Pass ``types`` to
        filter to specific component names; omit it for the full set with live usage counts.
        """

        schema = world_schema(actor)
        if types:
            wanted = set(types)
            components = {name: item for name, item in schema.components.items() if name in wanted}
        else:
            components = dict(schema.components)
        return {
            "ok": True,
            "world_epoch": schema.world_epoch,
            "components": {name: item.model_dump() for name, item in components.items()},
        }

    @play_tool
    def play_recent_events(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
        since: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return recent events the client's character caused or perceived in its room.

        Use this to observe outcomes of semi-turn-based commands: a queued command's
        execution or rejection (with reason) shows up here once it resolves. ``since`` is a
        watermark cursor; pass back the returned ``next_cursor`` to fetch only newer events.
        """

        controlled_or_requested_player(
            client_id,
            None,
            claim_id=claim_id,
            claim_secret=claim_secret,
        )
        return event_bridge.perceived_for_client(client_id, since=since, limit=limit)

    @play_tool
    def play_what_changed(
        client_id: str,
        since_epoch: int,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Summarize authoritative visible changes after one world-epoch watermark."""

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                None,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            result = actor.perspective_queries.execute(
                actor,
                "what_changed_since",
                {"epoch": since_epoch},
                actor_id=str(character),
                access="claim",
            ).model_dump(mode="json")
            events = result.get("result", {}).get("events", [])
            result["summary"] = f"{len(events)} visible change(s) since epoch {since_epoch}."
            result["next_actions"] = [
                "Call play_look to refresh the current situation.",
                "Use the returned world_epoch as the next watermark.",
            ]
            return result
        except (PermissionError, RuntimeError, ValueError, TimeoutError) as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    async def play_claim_character(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
        character_name: str | None = None,
        character_id: str | None = None,
        label: str = "",
        allow_child_claims: bool = False,
    ) -> dict[str, Any]:
        """Claim a suspended or named character for an MCP client id."""

        try:
            async with actor._lock:
                player(client_id)
                claim_secret = request_claim_secret(claim_secret)
                claimed = assign_mcp_controller(
                    actor,
                    claim_secrets=claim_secrets,
                    client_id=client_id,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
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

    @play_tool
    async def play_reclaim_character(
        client_id: str,
        claim_id: str,
        claim_secret: str,
    ) -> dict[str, Any]:
        """Resume active MCP control for the character already owned by this claim."""

        try:
            async with actor._lock:
                player(client_id)
                claim_secret = request_claim_secret(claim_secret)
                found = claimed_character_for(actor, client_id=client_id)
                if found is None:
                    raise RuntimeError("client does not own a character claim")
                claim = found[3]
                ensure_claim_secret(
                    claim_secrets,
                    claim,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
                )
                return assign_mcp_controller(
                    actor,
                    claim_secrets=claim_secrets,
                    client_id=client_id,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
                    character_id=claim.character_id,
                    label=claim.label,
                )
        except (PermissionError, RuntimeError) as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    async def play_release_control(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
        fallback_controller: str = "suspend",
        reason: str = "released by MCP client",
        model: str | None = None,
        provider: str = "ollama",
    ) -> dict[str, Any]:
        """Release active control to another controller while retaining the claim."""

        try:
            async with actor._lock:
                player(client_id)
                claim_secret = request_claim_secret(claim_secret)
                return release_mcp_controller(
                    actor,
                    claim_secrets=claim_secrets,
                    client_id=client_id,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
                    fallback_controller=fallback_controller,
                    reason=reason,
                    model=model,
                    provider=provider,
                )
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    async def play_release_claim(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Release the client's claim without changing the active controller."""

        try:
            async with actor._lock:
                player(client_id)
                claim_secret = request_claim_secret(claim_secret)
                return release_mcp_claim(
                    actor,
                    claim_secrets=claim_secrets,
                    client_id=client_id,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
                )
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    @_traced_tool
    async def play_send_command(
        client_id: str,
        command_type: str,
        payload: dict[str, Any] | None = None,
        character_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
        cost_action: int = 1,
        cost_focus: int = 0,
        lane: str = "world",
        on_insufficient_points: str = "queue",
        expires_at_epoch: int | None = None,
    ) -> dict[str, Any]:
        """Queue a world command from an MCP-controlled character."""

        try:
            character, controller, generation = controlled_or_requested_player(
                client_id,
                character_id,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            if command_type in CONTROL_COMMANDS:
                # Control verbs reassign the character's controller and bypass the
                # generation/ownership gates; they are a server orchestration primitive, not
                # a player action. MCP controller changes go through assign_mcp_controller /
                # release_mcp_controller, which validate claim ownership.
                raise ToolError(
                    f"control verb {command_type!r} cannot be sent through send_command; "
                    "use the controller claim/release tools"
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
        outcome = await actor.submit(command)
        if not outcome.accepted:
            return {
                "ok": False,
                "queued": False,
                "command_id": outcome.command_id,
                "character_id": command.character_id,
                "command_type": command.command_type,
                "reason": outcome.reason,
                "note": (
                    "Rejected at submission (invalid command). Fix the issue -- e.g. a "
                    "missing or unreachable target, a missing required argument, or a "
                    "missing skill/item -- and resend."
                ),
            }
        return {
            "ok": True,
            "queued": True,
            "command_id": command.command_id,
            "character_id": command.character_id,
            "command_type": command.command_type,
            "resolves_at_epoch": _next_tick_epoch(),
            "note": (
                "Queued only. Commands resolve on a later world tick and may still be "
                "rejected. Observe the outcome via play_recent_events (execution or "
                "CommandRejectedEvent with a reason) or play_pending_commands (still pending)."
            ),
        }

    @play_tool
    async def play_cancel_command(
        client_id: str,
        command_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Cancel one still-pending command for the controlled character."""

        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                None,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            command = await actor.cancel_command(str(character), command_id)
            if command is None:
                raise ToolError("command is not pending")
            return {
                "command_id": command_id,
                "status": "cancelled",
                "world_epoch": actor.epoch,
                "summary": f"Cancelled {command.command_type}.",
                "next_actions": ["Call play_pending_commands to review the remaining queue."],
            }
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @admin_tool
    @_traced_tool
    async def admin_patch_world(
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply a world editor patch. Requires world:admin scope."""

        admin()
        try:
            response = await patch_world(
                WorldPatchRequest.model_validate({"operations": operations})
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    def admin_list_controller_definitions() -> dict[str, Any]:
        """List registered scripts, behavior trees, and the authorable leaf library.

        Requires world:admin scope.
        """

        admin()
        if list_controller_definitions is None:
            raise ToolError("controller definition editing is not configured")
        return list_controller_definitions().model_dump(mode="json")

    @admin_tool
    async def admin_assign_controller(
        character_id: str,
        controller_id: str,
    ) -> dict[str, Any]:
        """Assign one existing controller to a character."""

        if assign_controller is None:
            raise ToolError("controller assignment is not configured")
        try:
            response = await assign_controller(
                ControllerAssignmentRequest(
                    character_id=character_id,
                    controller_id=controller_id,
                )
            )
            return response.model_dump(mode="json")
        except Exception as exc:
            raise ToolError(str(exc)) from exc

    @admin_tool
    async def admin_register_script(
        name: str,
        calls: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        """Register (or replace) a scripted-controller script and persist it.

        ``calls`` is an ordered list of ``{"name": verb, "arguments": {...}}`` tool calls.
        Requires world:admin scope.
        """

        admin()
        if register_script is None:
            raise ToolError("controller definition editing is not configured")
        try:
            spec = ScriptSpec.model_validate(
                {"name": name, "description": description, "calls": calls}
            )
            response = await register_script(spec)
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    async def admin_register_behavior(
        name: str,
        root: dict[str, Any],
        description: str = "",
    ) -> dict[str, Any]:
        """Register (or replace) a behavioral-controller behavior tree and persist it.

        ``root`` is a node: ``{"kind": "sequence"|"selector"|"condition"|"action", ...}``.
        Composite nodes carry ``children``; ``condition``/``action`` leaves name a library
        entry via ``ref`` with optional ``params``. Requires world:admin scope.
        """

        admin()
        if register_behavior is None:
            raise ToolError("controller definition editing is not configured")
        try:
            spec = BehaviorTreeSpec.model_validate(
                {"name": name, "description": description, "root": root}
            )
            response = await register_behavior(spec)
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    def admin_list_generators() -> dict[str, Any]:
        """List registered generation strategies and their seed behavior."""

        if list_generators is None:
            return {"generators": []}
        return list_generators()

    @admin_tool
    @_traced_tool
    async def admin_generate_world(
        seed: str | None = None,
        generator: str | None = None,
        max_rooms: int | None = None,
        confirm_reset: bool = False,
        save: bool = False,
    ) -> dict[str, Any]:
        """Start replacing the world through an enabled generator. Requires world:admin scope."""

        admin()
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

    @admin_tool
    async def admin_generation_status() -> dict[str, Any]:
        """Return the current async world generation job status. Requires world:admin scope."""

        admin()
        return (await generation_status()).model_dump(mode="json")

    @admin_tool
    @_traced_tool
    async def admin_generate_room(
        door_entity_id: str,
        direction: str | None = None,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate a room patch behind a door. Requires world:admin scope."""

        admin()
        try:
            response = await generate_room(
                WorldRoomGenerationRequest(
                    door_entity_id=door_entity_id,
                    direction=direction,
                    prompt=prompt,
                )
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    @_traced_tool
    async def admin_generate_character(
        room_entity_id: str,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate a character patch for a room. Requires world:admin scope."""

        admin()
        try:
            response = await generate_character(
                WorldCharacterGenerationRequest(room_entity_id=room_entity_id, prompt=prompt)
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    @_traced_tool
    async def admin_generate_item(
        container_entity_id: str,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate an item patch for a room or container. Requires world:admin scope."""

        admin()
        try:
            response = await generate_item(
                WorldItemGenerationRequest(
                    container_entity_id=container_entity_id,
                    prompt=prompt,
                )
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    @_traced_tool
    async def admin_generate_event(
        room_entity_id: str,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Generate a story event patch for a room. Requires world:admin scope."""

        admin()
        try:
            response = await generate_event(
                WorldEventGenerationRequest(room_entity_id=room_entity_id, prompt=prompt)
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @admin_tool
    async def admin_generate_image(
        entity_id: str,
        purpose: str = "portrait",
        template: str = "",
        extra: str = "",
        alpha: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """Generate (or regenerate) an image for an entity or history record.

        ``purpose`` is one of portrait/entity/sprite/event. Requires world:admin scope and a
        server configured with a ComfyUI image generation backend.
        """

        admin()
        if generate_image is None:
            raise ToolError("image generation is not configured")
        try:
            response = await generate_image(
                WorldImageGenerationRequest(
                    entity_id=entity_id,
                    purpose=purpose,
                    template=template,
                    extra=extra,
                    alpha=alpha,
                    force=force,
                )
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @play_tool
    @_traced_tool
    async def play_chat(
        client_id: str,
        message: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
        history_summary: str = "",
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Have a higher-level in-character exchange using the controlled claim."""

        if chat is None:
            raise ToolError("character chat is not configured")
        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                None,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            request = CharacterChatRequest.model_validate(
                {
                    "client_id": client_id,
                    "claim_id": claim_id,
                    "message": message,
                    "history_summary": history_summary,
                    "history": history or [],
                }
            )
            result = await chat(str(character), request, claim_secret)
            return {
                "summary": result.get("reply", "Character replied."),
                "world_epoch": result.get("world_epoch", actor.epoch),
                "reply": result.get("reply", ""),
                "action": result.get("action", {}),
                "next_actions": [
                    "Call play_recent_events if the reply queued an action.",
                    "Call play_look to refresh the situation.",
                ],
            }
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @play_tool
    @_traced_tool
    async def play_request_scene_image(
        client_id: str,
        character_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Illustrate the character's current room -- the MCP camera affordance.

        This is the player-facing equivalent of the camera button/reaction in the other
        clients (no admin scope required): it records the character's current scene as a
        world-history event and queues an image for it, reusing one already requested this
        tick. Resolves the client's controlled character unless ``character_id`` is given.
        """

        if scene_image is None:
            raise ToolError("image generation is not configured")
        try:
            character, _controller, _generation = controlled_or_requested_player(
                client_id,
                character_id,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        response = await scene_image(str(character))
        if response is None:
            raise ToolError("character has no room to illustrate")
        return response.model_dump(mode="json")

    try:
        for plugin in plugins:
            policy_registrar = PolicyRegistrar(plugin.id)
            for contribution in plugin.runtime.mcp:
                for registrar in contribution.registrars:
                    registrar(
                        policy_registrar,
                        actor,
                        event_bridge=event_bridge,
                        claim_secrets=claim_secrets,
                    )
    except Exception:
        event_bridge.close()
        raise

    del worldgen_options
    mcp_app = mcp.streamable_http_app()
    session_manager = getattr(mcp, "session_manager", None)
    if session_manager is not None:
        mcp_app.bunnyland_mcp_session_manager = session_manager
    mcp_app.bunnyland_mcp_event_bridge = event_bridge
    return mcp_app


__all__ = [
    "EVENTS_RESOURCE_URI",
    "MCP_MOUNT_PATH",
    "MCPEventBridge",
    "assign_mcp_controller",
    "create_bunnyland_mcp_app",
    "list_mcp_characters",
    "mcp_controlled_character",
    "mcp_enabled",
    "release_mcp_claim",
    "release_mcp_controller",
    "render_mcp_client_prompt",
]
