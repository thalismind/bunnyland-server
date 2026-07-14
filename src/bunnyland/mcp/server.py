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
from urllib.parse import quote, unquote

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
from ..server.client_ids import (
    ADMIN_CLIENT_IDS_ENV,
    CLIENT_ID_HEADER,
    PLAYER_CLIENT_IDS_ENV,
    configured_client_id_allowlist,
    require_allowed_client_id,
)
from ..server.models import (
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


MCP_MOUNT_PATH = "/mcp"
ADMIN_TOKEN_ENV = "BUNNYLAND_ADMIN_TOKEN"
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


def render_mcp_client_prompt(
    actor: WorldActor,
    *,
    claim_secrets: ClaimSecretRegistry | None = None,
    client_id: str,
    claim_id: str | None = None,
    claim_secret: str | None = None,
    fragment_providers: Sequence[Any] = (),
    persona_providers: Sequence[Any] = (),
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
    return {
        "ok": True,
        "client_id": client_id,
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
    admin_token: str | None,
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
    register_script: Callable[[ScriptSpec], Awaitable[ControllerDefinitionListResponse]]
    | None = None,
    register_behavior: Callable[[BehaviorTreeSpec], Awaitable[ControllerDefinitionListResponse]]
    | None = None,
    list_controller_definitions: Callable[[], ControllerDefinitionListResponse] | None = None,
    fragment_providers: Sequence[Any] = (),
    persona_providers: Sequence[Any] = (),
    worldgen_options: GenOptions | None = None,
    claim_secrets: ClaimSecretRegistry | None = None,
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

    def _request_admin_header() -> str | None:
        """The X-Bunnyland-Admin-Secret header from the active streamable-HTTP request, if
        any. nginx injects it after Basic auth so proxied callers need not pass the secret."""
        try:
            request = mcp.get_context().request_context.request
        except (LookupError, AttributeError, ValueError):
            return None
        headers = getattr(request, "headers", {}) or {}
        return headers.get("X-Bunnyland-Admin-Secret")

    def _request_client_id_header() -> str | None:
        try:
            request = mcp.get_context().request_context.request
        except (LookupError, AttributeError, ValueError):
            return None
        headers = getattr(request, "headers", {}) or {}
        return headers.get(CLIENT_ID_HEADER)

    def _request_claim_header(name: str) -> str | None:
        try:
            request = mcp.get_context().request_context.request
        except (LookupError, AttributeError, ValueError):
            return None
        headers = getattr(request, "headers", {}) or {}
        return headers.get(name)

    def admin(supplied: str | None) -> None:
        # Prefer the X-Bunnyland-Admin-Secret header the authenticating nginx proxy injects;
        # fall back to the explicit tool argument for direct (non-proxied) MCP clients.
        resolved = supplied or _request_admin_header()
        try:
            _require_admin_token(resolved, admin_token)
            require_allowed_client_id(
                _request_client_id_header(), allowed_admin_client_ids, "admin"
            )
        except PermissionError as exc:
            raise ToolError(str(exc)) from exc

    def player(client_id: str | None) -> str | None:
        try:
            return require_allowed_client_id(client_id, allowed_player_client_ids, "player")
        except PermissionError as exc:
            raise ToolError(str(exc)) from exc

    def controlled_or_requested_player(
        client_id: str,
        character_id: str | None,
        *,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> tuple[EntityId, EntityId, int]:
        player(client_id)
        return _controlled_or_requested_character(
            actor,
            claim_secrets,
            client_id,
            character_id,
            claim_id=claim_id,
            claim_secret=claim_secret,
        )

    @mcp.resource(
        EVENTS_RESOURCE_URI,
        name="recent_world_events",
        description="Recent Bunnyland domain events.",
        mime_type="application/json",
    )
    def recent_world_events_resource() -> str:
        return json.dumps({"ok": True, "events": event_bridge.recent_messages()})

    @mcp.resource(
        "bunnyland://clients/{client_id}/events",
        name="client_events",
        description="Recent Bunnyland domain events for an MCP-controlled client character.",
        mime_type="application/json",
    )
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

    @mcp.resource(
        "bunnyland://clients/{client_id}/prompt",
        name="client_prompt",
        description="Current Bunnyland prompt text for an MCP-controlled client character.",
        mime_type="text/plain",
    )
    def client_prompt_resource(client_id: str) -> str:
        player(client_id)
        return render_mcp_client_prompt(
            actor,
            claim_secrets=claim_secrets,
            client_id=client_id,
            claim_id=_request_claim_header("X-Bunnyland-Claim-Id"),
            claim_secret=_request_claim_header("X-Bunnyland-Claim-Secret"),
            fragment_providers=fragment_providers,
            persona_providers=persona_providers,
        )["prompt"]

    @mcp.tool()
    def list_characters() -> dict[str, Any]:
        """List claimable and controlled characters in the current world."""

        return {"ok": True, "characters": list_mcp_characters(actor)}

    @mcp.tool()
    @_traced_tool
    def world_snapshot_admin(admin_token: str | None = None) -> dict[str, Any]:
        """Return the full raw ECS world snapshot (large; admin/debug and persistence).

        This is the heavy dump of every entity and component, so it is admin-only: seeing
        the whole world at once would be cheating. For normal use prefer the scoped
        projections: ``character_view``/``room_view`` for a play-facing slice and
        ``world_overview_admin`` for the room-network map.
        """

        admin(admin_token)
        return serialize_world(actor, meta)

    @mcp.tool()
    @_traced_tool
    def world_overview_admin(admin_token: str | None = None) -> dict[str, Any]:
        """Return a slim, admin-only map of the whole room network (admin token required).

        Rooms with ids, titles, exits, and occupant/item counts -- the privileged graph the
        admin and web graph clients render. Withheld from players: seeing the full map would
        be cheating. For a player's own view use ``character_view`` (their perceived room).
        """

        admin(admin_token)
        return serialize_world_overview(actor).model_dump()

    @mcp.tool()
    @_traced_tool
    async def save_world_admin(admin_token: str | None = None) -> dict[str, Any]:
        """Save the current world to the configured persistent JSON/YAML file.

        Requires the MCP admin token. The server must have been started with a save path
        (the same configuration used by the REST ``/admin/world/save`` endpoint).
        """

        admin(admin_token)
        if save_path is None:
            raise ToolError("server was not started with --save")
        try:
            async with actor._lock:
                response = save_configured_world(actor, save_path, meta=meta)
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

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
    @_traced_tool
    def client_prompt(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Return the current Bunnyland prompt for an MCP-controlled client."""

        try:
            player(client_id)
            return render_mcp_client_prompt(
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

    @mcp.tool()
    @_traced_tool
    def character_view(
        client_id: str,
        character_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Return a structured, play-facing view for the client's character.

        Unlike ``client_prompt`` (narrative text), this returns machine-readable data: the
        room and its entities, inventory, action/focus points, and ``target_groups``
        resolving every targetable entity id. The full action catalogue is omitted here to
        keep the view small (progressive disclosure); use ``search_actions``/``list_actions``
        to find a verb and its argument schema, then read each argument's entity id from
        ``target_groups[argument.target_group]`` and call ``send_command``.
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
                "Action catalogue omitted; call search_actions(query) or list_actions(), "
                "then resolve ids from target_groups."
            )
            return data
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    @_traced_tool
    def query_world(
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

    @mcp.tool()
    def search_actions(query: str = "", limit: int = 30, mode: str = "substring") -> dict[str, Any]:
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

    @mcp.tool()
    def list_actions() -> dict[str, Any]:
        """Return the entire available action catalogue (every verb and its argument schema).

        This is large; prefer ``search_actions(query)`` for normal use. Useful when a client
        wants the complete set of verbs at once.
        """

        return serialize_action_search(actor, query="", limit=0).model_dump()

    @mcp.tool()
    @_traced_tool
    def examine(
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

    @mcp.tool()
    @_traced_tool
    def room_view(room_id: str) -> dict[str, Any]:
        """Return a structured view of one room: entities, exits, and sprites."""

        try:
            return serialize_room_projection(actor, room_id).model_dump()
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    def character_commands(
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

    @mcp.tool()
    def component_schema(types: list[str] | None = None) -> dict[str, Any]:
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

    @mcp.tool()
    def perceived_events(
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

    @mcp.tool()
    async def claim_character(
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

    @mcp.tool()
    async def release_character(
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

    @mcp.tool()
    async def release_claim(
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Release the client's claim without changing the active controller."""

        try:
            async with actor._lock:
                player(client_id)
                return release_mcp_claim(
                    actor,
                    claim_secrets=claim_secrets,
                    client_id=client_id,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
                )
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool()
    @_traced_tool
    async def send_command(
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
                "rejected. Observe the outcome via perceived_events (execution or "
                "CommandRejectedEvent with a reason) or character_commands (still pending)."
            ),
        }

    @mcp.tool()
    @_traced_tool
    async def patch_world_admin(
        operations: list[dict[str, Any]],
        admin_token: str | None = None,
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
    def list_controller_definitions_admin(admin_token: str | None = None) -> dict[str, Any]:
        """List registered scripts, behavior trees, and the authorable leaf library.

        Requires the MCP admin token.
        """

        admin(admin_token)
        if list_controller_definitions is None:
            raise ToolError("controller definition editing is not configured")
        return list_controller_definitions().model_dump(mode="json")

    @mcp.tool()
    async def register_script_admin(
        name: str,
        calls: list[dict[str, Any]],
        description: str = "",
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        """Register (or replace) a scripted-controller script and persist it.

        ``calls`` is an ordered list of ``{"name": verb, "arguments": {...}}`` tool calls.
        Requires the MCP admin token.
        """

        admin(admin_token)
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

    @mcp.tool()
    async def register_behavior_admin(
        name: str,
        root: dict[str, Any],
        description: str = "",
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        """Register (or replace) a behavioral-controller behavior tree and persist it.

        ``root`` is a node: ``{"kind": "sequence"|"selector"|"condition"|"action", ...}``.
        Composite nodes carry ``children``; ``condition``/``action`` leaves name a library
        entry via ``ref`` with optional ``params``. Requires the MCP admin token.
        """

        admin(admin_token)
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

    @mcp.tool()
    @_traced_tool
    async def generate_world_admin(
        seed: str | None = None,
        generator: str | None = None,
        max_rooms: int | None = None,
        confirm_reset: bool = False,
        save: bool = False,
        admin_token: str | None = None,
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
    async def world_generation_status_admin(admin_token: str | None = None) -> dict[str, Any]:
        """Return the current async world generation job status. Requires admin token."""

        admin(admin_token)
        return (await generation_status()).model_dump(mode="json")

    @mcp.tool()
    @_traced_tool
    async def generate_room_patch_admin(
        door_entity_id: str,
        direction: str | None = None,
        prompt: str = "",
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        """Generate a room patch behind a door. Requires admin token."""

        admin(admin_token)
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

    @mcp.tool()
    @_traced_tool
    async def generate_character_patch_admin(
        room_entity_id: str,
        prompt: str = "",
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        """Generate a character patch for a room. Requires admin token."""

        admin(admin_token)
        try:
            response = await generate_character(
                WorldCharacterGenerationRequest(room_entity_id=room_entity_id, prompt=prompt)
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @mcp.tool()
    @_traced_tool
    async def generate_item_patch_admin(
        container_entity_id: str,
        prompt: str = "",
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        """Generate an item patch for a room or container. Requires admin token."""

        admin(admin_token)
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

    @mcp.tool()
    @_traced_tool
    async def generate_event_patch_admin(
        room_entity_id: str,
        prompt: str = "",
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        """Generate a story event patch for a room. Requires admin token."""

        admin(admin_token)
        try:
            response = await generate_event(
                WorldEventGenerationRequest(room_entity_id=room_entity_id, prompt=prompt)
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        return response.model_dump(mode="json")

    @mcp.tool()
    async def generate_image_admin(
        entity_id: str,
        purpose: str = "portrait",
        template: str = "",
        extra: str = "",
        alpha: bool = False,
        force: bool = False,
        admin_token: str | None = None,
    ) -> dict[str, Any]:
        """Generate (or regenerate) an image for an entity or history record.

        ``purpose`` is one of portrait/entity/sprite/event. Requires the admin token and a
        server configured with a ComfyUI image generation backend.
        """

        admin(admin_token)
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

    @mcp.tool()
    @_traced_tool
    async def request_scene_image(
        client_id: str,
        character_id: str | None = None,
        claim_id: str | None = None,
        claim_secret: str | None = None,
    ) -> dict[str, Any]:
        """Illustrate the character's current room -- the MCP camera affordance.

        This is the player-facing equivalent of the camera button/reaction in the other
        clients (no admin token required): it records the character's current scene as a
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
    "release_mcp_claim",
    "release_mcp_controller",
    "render_mcp_client_prompt",
]
