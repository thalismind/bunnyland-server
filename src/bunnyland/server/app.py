"""FastAPI app factory for web clients."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from bunnyland.simpacks.toonsim.mechanics import SpriteImageComponent

from .. import telemetry
from ..claims import (
    CLIENT_KIND_WEB,
    ClaimSecretRegistry,
    add_claim,
    claim_client_matches,
    controller_claim,
    current_controller,
    ensure_claim_secret,
    matching_controller,
    normalize_claimed_controllers_without_secrets,
    remove_claim,
    transfer_claim,
)
from ..content import load_content_library
from ..core import (
    CharacterComponent,
    IdentityComponent,
    LLMControllerComponent,
    MemoryProfileComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from ..core.claim_timeout import apply_claim_timeout_settings, record_claim_activity
from ..core.controllers import ClaimedComponent, ClaimTimeoutComponent
from ..core.events import (
    CharacterClaimedEvent,
    ControllerChangedEvent,
    serialized_event_visible_to,
)
from ..core.perspective import PerspectiveQueryRequest, PerspectiveQueryResult
from ..core.world_actor import CONTROL_COMMANDS, WorldActor
from ..imagegen.components import PortraitImageComponent
from ..imagegen.media import (
    SEGMENT_PORTRAITS,
    SEGMENT_SPRITES,
    MediaStore,
)
from ..imagegen.scene import request_scene_image
from ..imagegen.spec import ImagePurpose
from ..llm_agents import (
    ControllerDefinitionStore,
    action_library_names,
    behavior_tree_names,
    condition_library_names,
    script_names,
)
from ..llm_agents.specs import BehaviorTreeSpec, ScriptSpec
from ..mcp import MCP_MOUNT_PATH, create_bunnyland_mcp_app, mcp_enabled
from ..persistence import WorldMeta
from ..plugins import collect_persona_fragments, collect_prompt_fragments
from ..worldgen import GenOptions, collect_generators
from .admin import idle_generation_status, save_configured_world, start_world_generation
from .character_chat import CharacterChatService
from .client_ids import (
    ADMIN_CLIENT_IDS_ENV,
    CLIENT_ID_HEADER,
    PLAYER_CLIENT_IDS_ENV,
    configured_client_id_allowlist,
    require_allowed_client_id,
)
from .models import (
    CharacterChatPendingResponse,
    CharacterChatRequest,
    CharacterChatResponse,
    CharacterChatStatusResponse,
    CharacterImageUploadResponse,
    CharacterListResponse,
    CharacterProjectionResponse,
    CharacterQueuedCommandsResponse,
    ClaimReleaseResponse,
    CommandCancelResponse,
    CommandRequest,
    CommandResponse,
    ControllerAssignmentRequest,
    ControllerDefinitionListResponse,
    DmProjectionResponse,
    EventImageRequest,
    FeatureStatusResponse,
    HealthResponse,
    MemoryCharactersResponse,
    MemoryCharacterView,
    MemoryDocumentResponse,
    MemoryDocumentsResponse,
    MemoryDocumentUpdateRequest,
    MemoryDocumentView,
    RecentEventsResponse,
    RoomProjectionResponse,
    StoredControllerDefinitions,
    WebControllerClaimRequest,
    WebControllerClaimResponse,
    WebControllerFallbackRequest,
    WebControllerFallbackResponse,
    WorldCharacterGenerationRequest,
    WorldCharacterGenerationResponse,
    WorldEventGenerationRequest,
    WorldEventGenerationResponse,
    WorldGenerateRequest,
    WorldGenerateResponse,
    WorldGenerationStatusResponse,
    WorldGeneratorInfo,
    WorldGeneratorListResponse,
    WorldImageGenerationRequest,
    WorldImageGenerationResponse,
    WorldItemGenerationRequest,
    WorldItemGenerationResponse,
    WorldLibraryResponse,
    WorldOverviewResponse,
    WorldPatchRequest,
    WorldPatchResponse,
    WorldRoomGenerationRequest,
    WorldRoomGenerationResponse,
    WorldRuntimeResponse,
    WorldSaveResponse,
    WorldSchemaResponse,
)
from .patches import WorldPatchError, apply_world_patch
from .schema import world_schema
from .serialization import (
    serialize_character_list,
    serialize_character_projection,
    serialize_character_queued_commands,
    serialize_dm_projection,
    serialize_entity,
    serialize_room_projection,
    serialize_world,
    serialize_world_overview,
)
from .subscriptions import EventStream
from .worldgen import (
    generate_character_patch,
    generate_event_patch,
    generate_item_patch,
    generate_room_patch,
)

WEBSOCKET_HEARTBEAT_SECONDS = 30.0
PLAYER_WEBSOCKET_AUTH_SECONDS = 5.0
UPLOAD_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
MAX_UPLOAD_IMAGE_BYTES = 10 * 1024 * 1024

if TYPE_CHECKING:
    from ..engine import GameLoop
    from ..imagegen.service import ImageGenService
    from ..plugins.model import Plugin
    from .subscriptions import EventSubscription

# Imported at module scope (not inside ``create_app``) so that FastAPI can resolve the
# ``websocket: WebSocket`` annotation on the route handler. Under ``from __future__ import
# annotations`` the hint is the string "WebSocket", which FastAPI looks up in this module's
# globals; a function-local import would leave it unresolvable and FastAPI would misread the
# parameter as a query field, closing every connection with a 403. Optional dependency, so
# fall back to ``None`` and raise a friendly error from ``create_app`` if it is missing.
try:
    from fastapi import (
        FastAPI,
        Header,
        HTTPException,
        Request,
        Response,
        WebSocket,
        WebSocketDisconnect,
    )
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
except ImportError:
    FastAPI = Header = HTTPException = Request = Response = None  # type: ignore[assignment, misc]
    WebSocket = WebSocketDisconnect = CORSMiddleware = JSONResponse = None  # type: ignore[assignment, misc]


ADMIN_TOKEN_ENV = "BUNNYLAND_ADMIN_TOKEN"
#: Header carrying the admin bearer secret. nginx injects it after Basic auth; it mirrors the
#: player-facing ``X-Bunnyland-Claim-Secret`` naming. Compared case-insensitively on read.
ADMIN_SECRET_HEADER = "X-Bunnyland-Admin-Secret"
logger = logging.getLogger("bunnyland.server")
GIT_HASH_ENV = "BUNNYLAND_GIT_HASH"


async def next_websocket_update(actor: WorldActor, subscription: EventSubscription) -> dict:
    try:
        return await asyncio.wait_for(
            subscription.queue.get(),
            timeout=WEBSOCKET_HEARTBEAT_SECONDS,
        )
    except TimeoutError:
        return {"type": "heartbeat", "data": {"world_epoch": actor.epoch}}


def _character_room_id(actor: WorldActor, character_id: str) -> str | None:
    parsed = parse_entity_id(character_id)
    if parsed is None or not actor.world.has_entity(parsed):
        return None
    room_id = container_of(actor.world.get_entity(parsed))
    return str(room_id) if room_id is not None else None


def player_update_for_message(
    actor: WorldActor,
    character_id: str,
    message: dict,
) -> dict | None:
    """Filter one internal broadcast into a safe player update frame."""
    if message.get("type") != "event":
        return {"type": "invalidate", "data": {"world_epoch": actor.epoch}}
    data = message.get("data")
    if not isinstance(data, dict):
        return None
    event = data.get("event")
    if not isinstance(event, dict):
        return None
    if serialized_event_visible_to(
        event,
        character_id=character_id,
        room_of=lambda candidate: _character_room_id(actor, candidate),
    ):
        return message
    if event.get("visibility") == "system":
        return {
            "type": "invalidate",
            "data": {"world_epoch": int(event.get("world_epoch") or actor.epoch)},
        }
    return None


def recent_player_updates(
    actor: WorldActor,
    character_id: str,
    messages: list[dict],
) -> list[dict]:
    return [
        update
        for message in messages
        if (update := player_update_for_message(actor, character_id, message)) is not None
    ]


async def next_player_update(
    actor: WorldActor,
    subscription: EventSubscription,
    character_id: str,
) -> dict:
    """Return the next safe frame, a resync after overflow, or an idle heartbeat."""
    if subscription.consume_dropped():
        return {"type": "resync", "data": {"world_epoch": actor.epoch}}
    deadline = asyncio.get_running_loop().time() + WEBSOCKET_HEARTBEAT_SECONDS
    while True:
        timeout = max(0, deadline - asyncio.get_running_loop().time())
        try:
            message = await asyncio.wait_for(subscription.queue.get(), timeout=timeout)
        except TimeoutError:
            return {"type": "heartbeat", "data": {"world_epoch": actor.epoch}}
        if subscription.consume_dropped():
            return {"type": "resync", "data": {"world_epoch": actor.epoch}}
        update = player_update_for_message(actor, character_id, message)
        if update is not None:
            return update


def create_app(
    actor: WorldActor,
    meta: WorldMeta | None = None,
    *,
    loop: GameLoop | None = None,
    save_path: str | Path | None = None,
    definitions_path: str | Path | None = None,
    worldgen_options: GenOptions | None = None,
    plugins: list[Plugin] | None = None,
    admin_token: str | None = None,
    player_client_ids: str | list[str] | None = None,
    admin_client_ids: str | list[str] | None = None,
    imagegen: ImageGenService | None = None,
    character_chat: CharacterChatService | None = None,
    claim_secrets: ClaimSecretRegistry | None = None,
    memory_store=None,
    title: str = "bunnyland",
):
    """Create the HTTP/websocket app around a live ``WorldActor``."""

    if FastAPI is None:
        raise RuntimeError(
            "bunnyland server API requires FastAPI; install the server dependencies first"
        )
    actor.configure_persistence(
        save_path=save_path,
        meta=meta,
        plugins=tuple(plugins or ()),
        plugin_context=getattr(actor.persistence, "plugin_context", None),
    )

    mcp_session_manager = None
    mcp_event_bridge = None

    @asynccontextmanager
    async def lifespan(_app):
        mcp_session_context = None
        try:
            if mcp_session_manager is not None:
                mcp_session_context = mcp_session_manager.run()
                await mcp_session_context.__aenter__()
            if imagegen is not None:
                # Throttled portrait/sprite backfill runs beside the loop (not in the tick),
                # filling in characters still missing an image, one request at a time.
                imagegen.start_backfill()
            yield
        finally:
            if mcp_session_context is not None:
                await mcp_session_context.__aexit__(None, None, None)
            if mcp_event_bridge is not None:
                mcp_event_bridge.close()
            if imagegen is not None:
                await imagegen.aclose()

    app = FastAPI(title=title, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    meta = meta or WorldMeta()
    actor.world_id = meta.world_id
    stream = EventStream(actor)
    actor.event_stream = stream
    claim_secrets = claim_secrets or ClaimSecretRegistry()
    normalize_claimed_controllers_without_secrets(actor, claim_secrets)
    allowed_player_client_ids = configured_client_id_allowlist(
        player_client_ids, PLAYER_CLIENT_IDS_ENV
    )
    allowed_admin_client_ids = configured_client_id_allowlist(
        admin_client_ids, ADMIN_CLIENT_IDS_ENV
    )
    generator_registry = collect_generators(plugins or ())
    generation_job = None
    memory_store = memory_store or getattr(actor, "memory_store", None)
    media_store = (
        (getattr(imagegen, "media", None) if imagegen is not None else None)
        or getattr(actor, "media_service", None)
        or MediaStore(os.environ.get("BUNNYLAND_MEDIA_DIR", "media").strip() or "media")
    )
    actor.media_service = media_store
    # Editor-loaded scripted/behavioral controller definitions: register any already on disk
    # so a restarted server keeps the scripts and behavior trees the editor previously saved.
    definition_store = ControllerDefinitionStore(
        definitions_path, action_definitions=actor.action_definitions()
    )
    definition_store.load()

    def _require_imagegen() -> ImageGenService:
        if imagegen is None:
            raise HTTPException(status_code=409, detail="image generation is not configured")
        return imagegen

    def _require_memory_store():
        if memory_store is None:
            raise HTTPException(status_code=409, detail="memory is not configured")
        return memory_store

    def _parse_purpose(value: str) -> ImagePurpose:
        try:
            return ImagePurpose(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid image purpose {value!r}") from exc

    def _require_allowed_player_client_id(client_id: str | None) -> str | None:
        try:
            return require_allowed_client_id(client_id, allowed_player_client_ids, "player")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def _require_allowed_admin_client_id(client_id: str | None) -> str | None:
        try:
            return require_allowed_client_id(client_id, allowed_admin_client_ids, "admin")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def _image_response(job) -> WorldImageGenerationResponse:
        return WorldImageGenerationResponse(
            world_epoch=actor.epoch,
            job_id=job.job_id,
            status=job.status,
            entity_id=job.entity_id,
            purpose=job.purpose.value,
            url=job.url,
            alpha_url=job.alpha_url,
            error=job.error,
        )

    def _git_hash() -> str:
        hash_value = os.environ.get(GIT_HASH_ENV, "").strip()
        return hash_value if hash_value else "unknown"

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            world_epoch=actor.epoch,
            git_hash=_git_hash(),
            features=FeatureStatusResponse(
                mcp=mcp_enabled(plugins),
                character_chat=character_chat is not None,
                character_sheets=True,
                image_generation=imagegen is not None,
            ),
        )

    @app.get("/world/snapshot")
    async def world_snapshot(
        admin_token: str | None = Header(
            default=None,
            alias=ADMIN_SECRET_HEADER,
        ),
        admin_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> dict:
        # The raw ECS dump reveals the whole world; gate it like the DM/overview
        # projections so it is not a back door around the per-room player views.
        _require_projection_admin(admin_token, admin_client_id)
        with telemetry.span("world.snapshot"):
            return serialize_world(actor, meta)

    @app.get("/world/characters", response_model=CharacterListResponse)
    async def world_character_list() -> CharacterListResponse:
        # The claim lobby: ids and names only, so a player can pick a character without
        # the admin-gated full snapshot. Per-character state stays behind the projections.
        return serialize_character_list(actor)

    @app.get("/world/character/{id}", response_model=CharacterProjectionResponse)
    async def world_character_projection(
        id: str,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> CharacterProjectionResponse:
        with telemetry.span("character.projection", {"character.id": id}):
            _require_claim_secret(id, claim_id=claim_id, claim_secret=claim_secret)
            return serialize_character_projection(actor, id)

    @app.get("/world/character/{id}/commands", response_model=CharacterQueuedCommandsResponse)
    async def world_character_queued_commands(
        id: str,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> CharacterQueuedCommandsResponse:
        with telemetry.span("character.queued_commands", {"character.id": id}):
            _require_claim_secret(id, claim_id=claim_id, claim_secret=claim_secret)
            return serialize_character_queued_commands(actor, id, **_runtime_timing())

    @app.post(
        "/world/character/{id}/query",
        response_model=PerspectiveQueryResult,
    )
    async def world_character_query(
        id: str,
        request: PerspectiveQueryRequest,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> PerspectiveQueryResult:
        _require_claim_secret(
            id,
            claim_id=claim_id,
            claim_secret=claim_secret,
            require_claimed=True,
        )
        try:
            return actor.perspective_queries.execute(
                actor,
                request.query,
                request.arguments,
                actor_id=id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/world/room/{id}", response_model=RoomProjectionResponse)
    async def world_room_projection(id: str) -> RoomProjectionResponse:
        try:
            with telemetry.span("room.projection", {"room.id": id}):
                return serialize_room_projection(actor, id)
        except ValueError as exc:
            detail = str(exc)
            status = 400 if detail == "entity is not a room" else 404
            raise HTTPException(status_code=status, detail=detail) from exc

    def _require_projection_admin(supplied: str | None, admin_client_id: str | None = None) -> None:
        expected = (admin_token or os.environ.get(ADMIN_TOKEN_ENV) or "").strip()
        if not expected:
            raise HTTPException(status_code=403, detail=f"{ADMIN_TOKEN_ENV} is not configured")
        if supplied != expected:
            raise HTTPException(status_code=403, detail="invalid admin token")
        _require_allowed_admin_client_id(admin_client_id)

    @app.middleware("http")
    async def _enforce_admin_secret(request: Request, call_next):
        # Single choke point for the whole /admin/* surface so a newly added admin route
        # cannot silently ship unauthenticated. Routes that touch the claim graph
        # (/admin/controllers/assign, /admin/world) are reassignment primitives, so this
        # must fail closed: an unset BUNNYLAND_ADMIN_TOKEN rejects rather than opens. The
        # privileged /world/{snapshot,dm,overview} projections and the /world/updates
        # WebSocket are not under /admin and keep their own explicit guard. nginx injects
        # the admin secret after Basic auth; direct callers must supply it themselves.
        if request.url.path.startswith("/admin") and request.method != "OPTIONS":
            try:
                _require_projection_admin(
                    request.headers.get(ADMIN_SECRET_HEADER.lower()),
                    request.headers.get(CLIENT_ID_HEADER.lower()),
                )
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    from ..foundation.media.plugin import plugin as media_plugin

    router_plugins = [
        media_plugin(),
        *(plugin for plugin in (plugins or ()) if plugin.id != "bunnyland.media"),
    ]
    for plugin in router_plugins:
        for router_factory in plugin.runtime.server_routers:
            router_factory(
                app,
                actor,
                meta=meta,
                loop=loop,
                save_path=save_path,
                definitions_path=definitions_path,
                worldgen_options=worldgen_options,
                plugins=plugins or (),
                media_store=media_store,
            )

    def _character_entity(character_id: str):
        parsed = parse_entity_id(character_id)
        if parsed is None or not actor.world.has_entity(parsed):
            raise HTTPException(status_code=404, detail="character does not exist")
        character = actor.world.get_entity(parsed)
        if not character.has_component(CharacterComponent):
            raise HTTPException(status_code=400, detail="entity is not a character")
        return character

    def _require_claim_secret(
        character_id: str,
        *,
        claim_id: str | None = None,
        claim_secret: str | None = None,
        require_claimed: bool = False,
    ):
        character = _character_entity(character_id)
        found = current_controller(actor, character)
        if found is None:
            if require_claimed:
                raise HTTPException(status_code=403, detail="character is not claimed")
            return None
        controller, _edge = found
        claim = controller_claim(controller)
        if claim is None:
            if require_claimed:
                raise HTTPException(status_code=403, detail="character is not claimed")
            return None
        try:
            ensure_claim_secret(
                claim_secrets,
                claim,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        _require_allowed_player_client_id(claim.client_id)
        return character, controller, claim

    def _resume_web_claim_for_command(command, claim_context):
        character, controller, claim = claim_context
        if controller.has_component(WebControllerComponent):
            web = controller.get_component(WebControllerComponent)
            if web.client_id != claim.client_id:
                raise HTTPException(
                    status_code=409,
                    detail="claim is not active for this web client",
                )
            return command
        web_controller = _web_controller_for_client(claim.client_id)
        if web_controller is None:
            web_controller = spawn_entity(
                actor.world,
                [WebControllerComponent(client_id=claim.client_id, label=claim.label or "web")],
            )
        transfer_claim(controller, web_controller)
        add_claim(
            web_controller,
            client_kind=CLIENT_KIND_WEB,
            client_id=claim.client_id,
            character_id=claim.character_id,
            label=claim.label,
            claim_id=claim.claim_id,
            now_unix=claim.claimed_at_unix,
        )
        generation = actor.assign_controller(character.id, web_controller.id)
        record_claim_activity(web_controller, now_unix=int(time.time()))
        if character.has_component(SuspendedComponent):
            character.remove_component(SuspendedComponent)
        return replace(
            command,
            controller_id=str(web_controller.id),
            controller_generation=generation,
        )

    def _claim_secret(request) -> str | None:
        return getattr(request, "_claim_secret", None)

    def _with_claim_secret(request, claim_secret: str | None):
        if not isinstance(claim_secret, str):
            claim_secret = None
        request._claim_secret = claim_secret
        return request

    def _client_id_header_value(client_id: str | None) -> str | None:
        if not isinstance(client_id, str):
            return None
        normalized = client_id.strip()
        return normalized or None

    def _with_player_client_id(request, client_id: str | None):
        normalized = _client_id_header_value(client_id)
        if normalized is None:
            return request
        data = request.model_dump()
        data["client_id"] = normalized
        try:
            return request.__class__.model_validate(data)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

    def _with_player_request_context(
        request,
        claim_secret: str | None,
        client_id: str | None,
    ):
        request = _with_player_client_id(request, client_id)
        return _with_claim_secret(request, claim_secret)

    def _claimed_controller_for_web_request(request: WebControllerFallbackRequest):
        character = _character_entity(request.character_id)
        client_id = request.client_id.strip()
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id must not be blank")
        _require_allowed_player_client_id(client_id)
        found = current_controller(actor, character)
        if found is None:
            raise HTTPException(status_code=409, detail="character has no controller")
        controller, edge = found
        claim = controller_claim(controller)
        if claim is None:
            raise HTTPException(status_code=409, detail="character is not claimed")
        if not claim_client_matches(claim, client_id):
            raise HTTPException(status_code=409, detail="character is claimed by another client")
        try:
            ensure_claim_secret(
                claim_secrets,
                claim,
                claim_id=request.claim_id,
                claim_secret=_claim_secret(request),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return character, controller, edge, claim

    def _existing_controller(controller_id: str):
        parsed = parse_entity_id(controller_id)
        if parsed is None or not actor.world.has_entity(parsed):
            return None
        kind = actor._controller_kind(parsed)
        if kind == "unknown":
            raise HTTPException(status_code=400, detail="entity is not a controller")
        return actor.world.get_entity(parsed), kind

    def _fallback_controller(fallback: str, timeout: ClaimTimeoutComponent):
        selected = (
            fallback.strip() if fallback and fallback.strip() else timeout.fallback_controller
        )
        existing = _existing_controller(selected)
        if existing is not None:
            return existing
        normalized = selected.strip().lower().replace("_", "-")
        if normalized in {"suspend", "suspended", "offline"}:
            controller = spawn_entity(
                actor.world,
                [SuspendedControllerComponent(reason=timeout.fallback_reason)],
            )
            return controller, "suspended"
        if normalized in {"llm", "ai", "agent"}:
            controller = spawn_entity(
                actor.world,
                [
                    LLMControllerComponent(
                        profile_name=timeout.llm_profile_name or "default",
                        model=timeout.llm_model
                        or os.environ.get("BUNNYLAND_CHARACTER_MODEL", "deepseek-v4-flash"),
                        provider=timeout.llm_provider or "ollama",
                    )
                ],
            )
            return controller, "llm"
        raise HTTPException(status_code=400, detail="fallback_controller is not a controller")

    @app.get("/world/dm/{id}", response_model=DmProjectionResponse)
    async def world_dm_projection(
        id: str,
        admin_token: str | None = Header(
            default=None,
            alias=ADMIN_SECRET_HEADER,
        ),
        admin_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> DmProjectionResponse:
        _require_projection_admin(admin_token, admin_client_id)
        try:
            with telemetry.span("dm.projection", {"dm.id": id}):
                return serialize_dm_projection(actor, id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/world/overview", response_model=WorldOverviewResponse)
    async def world_overview(
        admin_token: str | None = Header(
            default=None,
            alias=ADMIN_SECRET_HEADER,
        ),
        admin_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> WorldOverviewResponse:
        _require_projection_admin(admin_token, admin_client_id)
        with telemetry.span("world.overview"):
            return serialize_world_overview(actor)

    @app.get("/world/schema", response_model=WorldSchemaResponse)
    async def get_world_schema() -> WorldSchemaResponse:
        return world_schema(actor)

    @app.get("/world/library", response_model=WorldLibraryResponse)
    async def get_world_library() -> WorldLibraryResponse:
        return WorldLibraryResponse.model_validate(load_content_library().model_dump(mode="json"))

    @app.get("/world/events/recent", response_model=RecentEventsResponse)
    async def recent_events(
        admin_token: str | None = Header(default=None, alias=ADMIN_SECRET_HEADER),
        admin_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> RecentEventsResponse:
        _require_projection_admin(admin_token, admin_client_id)
        return RecentEventsResponse(events=stream.recent_messages())

    @app.get(
        "/world/character/{id}/events/recent",
        response_model=RecentEventsResponse,
    )
    async def character_recent_events(
        id: str,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> RecentEventsResponse:
        _require_claim_secret(id, claim_id=claim_id, claim_secret=claim_secret)
        return RecentEventsResponse(
            events=recent_player_updates(actor, id, stream.recent_messages())
        )

    @app.get("/world/chat/status", response_model=CharacterChatStatusResponse)
    async def world_chat_status() -> CharacterChatStatusResponse:
        return CharacterChatStatusResponse(
            world_epoch=actor.epoch,
            enabled=character_chat is not None,
            allowed_tools=character_chat.allowed_tools if character_chat is not None else [],
        )

    @app.post("/world/character/{id}/chat", response_model=CharacterChatResponse)
    async def world_character_chat(
        id: str,
        request: CharacterChatRequest,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
        player_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> CharacterChatResponse:
        request = _with_player_request_context(request, claim_secret, player_client_id)
        if character_chat is None:
            raise HTTPException(status_code=409, detail="character chat is not enabled")
        _require_allowed_player_client_id(request.client_id)
        _require_claim_secret(
            id,
            claim_id=request.claim_id,
            claim_secret=_claim_secret(request),
        )
        try:
            with telemetry.span("character.chat", {"character.id": id}) as span:
                try:
                    response = await character_chat.chat(id, request)
                except Exception as exc:
                    span.record_exception(exc)
                    telemetry.mark_span_error(str(exc), span)
                    raise
                telemetry.mark_span_ok(span)
                return response
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            detail = str(exc)
            status = 400 if detail == "entity is not a character" else 404
            raise HTTPException(status_code=status, detail=detail) from exc

    @app.get(
        "/world/character/{id}/chat/pending/{command_id}",
        response_model=CharacterChatPendingResponse,
    )
    async def world_character_chat_pending(
        id: str,
        command_id: str,
        client_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
        player_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> CharacterChatPendingResponse:
        if character_chat is None:
            raise HTTPException(status_code=409, detail="character chat is not enabled")
        client_id = _client_id_header_value(player_client_id) or client_id
        _require_allowed_player_client_id(client_id)
        _require_claim_secret(id, claim_id=claim_id, claim_secret=claim_secret)
        try:
            with telemetry.span(
                "character.chat.pending",
                {"character.id": id, "command.id": command_id},
            ) as span:
                try:
                    response = await character_chat.pending_result(id, client_id, command_id)
                except Exception as exc:
                    span.record_exception(exc)
                    telemetry.mark_span_error(str(exc), span)
                    raise
                telemetry.mark_span_ok(span)
                return response
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _runtime_timing() -> dict:
        now = time.time()
        tick_seconds = getattr(loop, "tick_seconds", None) if loop is not None else None
        time_scale = getattr(loop, "time_scale", None) if loop is not None else None
        next_tick_at_unix = getattr(loop, "next_tick_at_unix", None) if loop is not None else None
        if (
            next_tick_at_unix is None
            and tick_seconds is not None
            and loop is not None
            and getattr(loop, "running", False)
            and not getattr(loop, "paused", False)
        ):
            next_tick_at_unix = now + float(tick_seconds)
        return {
            "generated_at_unix": now,
            "next_tick_at_unix": next_tick_at_unix,
            "tick_seconds": float(tick_seconds) if tick_seconds is not None else None,
            "time_scale": float(time_scale) if time_scale is not None else None,
            "game_seconds_per_tick": (
                float(tick_seconds) * float(time_scale)
                if tick_seconds is not None and time_scale is not None
                else None
            ),
        }

    def _runtime_response() -> WorldRuntimeResponse:
        if loop is None:
            raise HTTPException(status_code=409, detail="server runtime is not attached")
        return WorldRuntimeResponse(
            world_epoch=actor.epoch,
            paused=loop.paused,
            running=loop.running,
            **_runtime_timing(),
        )

    def _memory_document_view(document) -> MemoryDocumentView:
        return MemoryDocumentView(
            id=document.id,
            document=document.document,
            metadata=dict(document.metadata),
        )

    def _memory_characters_response() -> MemoryCharactersResponse:
        characters = []
        query = actor.world.query().with_all(
            [CharacterComponent, IdentityComponent, MemoryProfileComponent]
        )
        for character in query.execute_entities():
            identity = character.get_component(IdentityComponent)
            profile = character.get_component(MemoryProfileComponent)
            characters.append(
                MemoryCharacterView(
                    character_id=str(character.id),
                    name=identity.name,
                    private_collection=profile.vector_collection,
                    shared_collections=list(profile.shared_collections),
                )
            )
        characters.sort(key=lambda item: (item.name.lower(), item.character_id))
        return MemoryCharactersResponse(world_epoch=actor.epoch, characters=characters)

    def _memory_documents_response(collection: str) -> MemoryDocumentsResponse:
        store = _require_memory_store()
        documents = [
            _memory_document_view(document) for document in store.list_documents(collection)
        ]
        return MemoryDocumentsResponse(
            world_epoch=actor.epoch,
            collection=collection,
            documents=documents,
        )

    def _memory_update_response(
        collection: str,
        note_id: str,
        request: MemoryDocumentUpdateRequest,
    ) -> MemoryDocumentResponse:
        store = _require_memory_store()
        document = store.update_document(
            collection,
            note_id,
            document=request.document,
            metadata=request.metadata,
        )
        if document is None:
            raise HTTPException(status_code=404, detail="memory document not found")
        return MemoryDocumentResponse(
            world_epoch=actor.epoch,
            collection=collection,
            document=_memory_document_view(document),
        )

    def _memory_create_response(
        collection: str,
        request: MemoryDocumentUpdateRequest,
    ) -> MemoryDocumentResponse:
        store = _require_memory_store()
        document = store.create_document(
            collection,
            document=request.document,
            metadata=request.metadata,
        )
        return MemoryDocumentResponse(
            world_epoch=actor.epoch,
            collection=collection,
            document=_memory_document_view(document),
        )

    def _delete_memory_document(collection: str, note_id: str) -> dict:
        store = _require_memory_store()
        if not store.delete(collection, note_id):
            raise HTTPException(status_code=404, detail="memory document not found")
        return {"ok": True, "schema_version": 1, "world_epoch": actor.epoch}

    async def _cancel_command_request(
        character_id: str,
        command_id: str,
        controller_id: str,
        controller_generation: int,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> CommandCancelResponse:
        _require_claim_secret(
            character_id,
            claim_id=claim_id,
            claim_secret=claim_secret,
            require_claimed=True,
        )
        parsed_character = parse_entity_id(character_id)
        parsed_controller = parse_entity_id(controller_id)
        if (
            parsed_controller is None
            or actor.current_generation(parsed_character, parsed_controller)
            != controller_generation
        ):
            raise HTTPException(status_code=409, detail="stale controller generation")
        command = await actor.cancel_command(character_id, command_id)
        if command is None:
            return CommandCancelResponse(
                ok=False,
                command_id=command_id,
                cancelled=False,
                reason="command not found",
            )
        return CommandCancelResponse(ok=True, command_id=command_id, cancelled=True)

    async def _submit_command_request(request: CommandRequest) -> CommandResponse:
        if request.command_type in CONTROL_COMMANDS:
            # Control verbs reassign a character's controller (spec 7.4) and deliberately
            # bypass the generation/ownership gates that protect normal actions, taking their
            # target controller straight from the payload. They are a server orchestration
            # primitive, not a player action: web clients change controllers through the
            # dedicated /world/controllers/web/* endpoints, which validate that the caller
            # owns the claim. Accepting them on the generic command surface would let any
            # claim holder repoint their character at an arbitrary controller entity.
            raise HTTPException(
                status_code=400,
                detail="control verbs are not accepted here; use the web controller endpoints",
            )
        claim_context = _require_claim_secret(
            request.character_id,
            claim_id=request.claim_id,
            claim_secret=_claim_secret(request),
            require_claimed=True,
        )
        command = request.to_submitted(submitted_at_epoch=actor.epoch)
        async with actor._lock:
            command = _resume_web_claim_for_command(command, claim_context)
        outcome = await actor.submit(command)
        return CommandResponse(
            queued=outcome.accepted,
            command_id=outcome.command_id,
            reason=outcome.reason,
        )

    def _web_claim_response(
        request: WebControllerFallbackRequest,
        *,
        controller,
        claim: ClaimedComponent,
        generation: int,
        claim_secret: str,
    ) -> WebControllerFallbackResponse:
        timeout = controller.get_component(ClaimTimeoutComponent)
        return WebControllerFallbackResponse(
            character_id=request.character_id,
            controller_id=str(controller.id),
            controller_generation=generation,
            claim_id=claim.claim_id,
            claim_secret=claim_secret,
            fallback_controller=timeout.fallback_controller,
            timeout_seconds=timeout.timeout_seconds,
        )

    def _web_controller_for_client(client_id: str):
        return matching_controller(
            actor,
            WebControllerComponent,
            lambda controller: controller.client_id == client_id,
        )

    async def _claim_web_controller_request(
        request: WebControllerClaimRequest,
    ) -> WebControllerClaimResponse:
        character_id = parse_entity_id(request.character_id)
        if character_id is None or not actor.world.has_entity(character_id):
            raise HTTPException(status_code=404, detail="character does not exist")
        character = actor.world.get_entity(character_id)
        if not character.has_component(CharacterComponent):
            raise HTTPException(status_code=400, detail="entity is not a character")

        client_id = request.client_id.strip()
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id must not be blank")
        _require_allowed_player_client_id(client_id)
        label = request.label.strip() or "web"

        with telemetry.span(
            "controller.web_claim",
            {
                "character.id": request.character_id,
                "client.id": client_id,
                "client.label": label,
            },
        ) as span:
            created = False
            async with actor._lock:
                active = current_controller(actor, character)
                active_controller = active[0] if active is not None else None
                active_claim = (
                    controller_claim(active_controller) if active_controller is not None else None
                )
                claim_id = None
                claim_secret = _claim_secret(request)
                validated_claim_secret = False
                if active_claim is not None:
                    if not claim_client_matches(active_claim, client_id):
                        raise HTTPException(
                            status_code=409,
                            detail="character is already claimed",
                        )
                    try:
                        ensure_claim_secret(
                            claim_secrets,
                            active_claim,
                            claim_id=request.claim_id,
                            claim_secret=_claim_secret(request),
                        )
                    except PermissionError as exc:
                        raise HTTPException(status_code=403, detail=str(exc)) from exc
                    validated_claim_secret = True
                    claim_id = active_claim.claim_id
                    claim_secret = claim_secrets.secret(active_claim.claim_id)

                controller = _web_controller_for_client(client_id)
                if controller is not None:
                    existing_claim = controller_claim(controller)
                    if existing_claim is not None and existing_claim.character_id != str(
                        character_id
                    ):
                        controller = None
                if controller is None:
                    created = True
                    controller = spawn_entity(
                        actor.world,
                        [WebControllerComponent(client_id=client_id, label=label)],
                    )
                if active_claim is not None and active_controller is not None:
                    transfer_claim(active_controller, controller)
                claim = add_claim(
                    controller,
                    client_kind=CLIENT_KIND_WEB,
                    client_id=client_id,
                    character_id=str(character_id),
                    label=label,
                    claim_id=claim_id,
                    now_unix=int(time.time()),
                )
                if (
                    not validated_claim_secret
                    or claim_secret is None
                    or not claim_secrets.has_secret(claim.claim_id)
                ):
                    claim_secret = claim_secrets.issue(claim.claim_id)
                apply_claim_timeout_settings(
                    controller,
                    now_unix=int(time.time()),
                    fallback_controller=request.fallback_controller,
                    fallback_reason=request.fallback_reason,
                    llm_profile_name=request.llm_profile_name,
                    llm_model=request.llm_model,
                    llm_provider=request.llm_provider,
                    timeout_seconds=request.timeout_seconds,
                    reset_activity=True,
                )

                generation = actor.current_generation(character_id, controller.id)
                assigned = generation is None
                if generation is None:
                    generation = actor.assign_controller(character_id, controller.id)
                    if character.has_component(SuspendedComponent):
                        character.remove_component(SuspendedComponent)
                    await actor.bus.publish(
                        ControllerChangedEvent(
                            **actor._event_base(
                                actor_id=str(character_id),
                                generation=generation,
                                controller_kind="web",
                            )
                        )
                    )
                    await actor.bus.publish(
                        CharacterClaimedEvent(
                            **actor._event_base(
                                actor_id=str(character_id),
                                character_id=str(character_id),
                                controller_id=str(controller.id),
                                generation=generation,
                            )
                        )
                    )

            timeout = controller.get_component(ClaimTimeoutComponent)
            span.set_attribute("controller.id", str(controller.id))
            span.set_attribute("controller.generation", generation)
            span.set_attribute("controller.created", created)
            span.set_attribute("controller.assigned", assigned)
            span.set_attribute("claim.fallback_controller", timeout.fallback_controller)
            span.set_attribute("claim.timeout_seconds", timeout.timeout_seconds)
            logger.info(
                "web claim character=%s controller=%s generation=%s "
                "client_id=%s label=%s assigned=%s created=%s",
                character_id,
                controller.id,
                generation,
                client_id,
                label,
                assigned,
                created,
            )

            stream.broadcast({"type": "snapshot", "data": serialize_world(actor, meta)})
            response = _web_claim_response(
                request,
                controller=controller,
                claim=claim,
                generation=generation,
                claim_secret=claim_secret or "",
            )
            return WebControllerClaimResponse(**response.model_dump())

    async def _web_controller_fallback_request(
        request: WebControllerFallbackRequest,
    ) -> WebControllerFallbackResponse:
        character, controller, edge, claim = _claimed_controller_for_web_request(request)
        client_id = request.client_id.strip()

        with telemetry.span(
            "controller.web_fallback",
            {"character.id": request.character_id, "client.id": client_id},
        ) as span:
            async with actor._lock:
                apply_claim_timeout_settings(
                    controller,
                    now_unix=int(time.time()),
                    fallback_controller=request.fallback_controller,
                    fallback_reason=request.fallback_reason,
                    llm_profile_name=request.llm_profile_name,
                    llm_model=request.llm_model,
                    llm_provider=request.llm_provider,
                    timeout_seconds=request.timeout_seconds,
                    reset_activity=False,
                )
                timeout = controller.get_component(ClaimTimeoutComponent)
                span.set_attribute("controller.id", str(controller.id))
                span.set_attribute("controller.generation", edge.generation)
                span.set_attribute("claim.fallback_controller", timeout.fallback_controller)
                span.set_attribute("claim.timeout_seconds", timeout.timeout_seconds)
                logger.info(
                    "web claim fallback character=%s controller=%s generation=%s "
                    "client_id=%s fallback=%s timeout_seconds=%s",
                    character.id,
                    controller.id,
                    edge.generation,
                    client_id,
                    timeout.fallback_controller,
                    timeout.timeout_seconds,
                )
                return _web_claim_response(
                    request,
                    controller=controller,
                    claim=claim,
                    generation=edge.generation,
                    claim_secret=claim_secrets.secret(claim.claim_id) or "",
                )

    async def _release_web_controller_to_fallback_request(
        request: WebControllerFallbackRequest,
    ) -> WebControllerFallbackResponse:
        character, controller, _edge, claim = _claimed_controller_for_web_request(request)
        timeout = (
            controller.get_component(ClaimTimeoutComponent)
            if controller.has_component(ClaimTimeoutComponent)
            else apply_claim_timeout_settings(
                controller,
                now_unix=int(time.time()),
                fallback_controller=request.fallback_controller,
            )
        )
        fallback = request.fallback_controller or timeout.fallback_controller
        async with actor._lock:
            new_controller, kind = _fallback_controller(fallback, timeout)
            transfer_claim(controller, new_controller)
            if kind == "suspended":
                generation = actor.suspend(
                    character.id,
                    new_controller.id,
                    reason=timeout.fallback_reason,
                )
            else:
                generation = actor.assign_controller(character.id, new_controller.id)
                if character.has_component(SuspendedComponent):
                    character.remove_component(SuspendedComponent)
            await actor.bus.publish(
                ControllerChangedEvent(
                    **actor._event_base(
                        actor_id=str(character.id),
                        generation=generation,
                        controller_kind=kind,
                    )
                )
            )
        return WebControllerFallbackResponse(
            character_id=str(character.id),
            controller_id=str(new_controller.id),
            controller_generation=generation,
            claim_id=claim.claim_id,
            claim_secret=claim_secrets.secret(claim.claim_id) or "",
            fallback_controller=kind,
            timeout_seconds=timeout.timeout_seconds,
        )

    async def _release_web_claim_request(
        request: WebControllerFallbackRequest,
    ) -> ClaimReleaseResponse:
        character, controller, _edge, claim = _claimed_controller_for_web_request(request)
        remove_claim(controller, claim_secrets)
        return ClaimReleaseResponse(
            character_id=str(character.id),
            controller_id=str(controller.id),
            claim_id=claim.claim_id,
        )

    async def _patch_world_request(request: WorldPatchRequest) -> WorldPatchResponse:
        try:
            with telemetry.span("world.patch", {"operation.count": len(request.operations)}):
                async with actor._lock:
                    response = apply_world_patch(actor, request)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stream.broadcast(
            {
                "type": "patch",
                "data": {
                    "world_epoch": response.world_epoch,
                    "changed_entities": [entity["id"] for entity in response.changed_entities],
                    "deleted_entities": response.deleted_entities,
                },
            }
        )
        return response

    async def _assign_controller_request(
        request: ControllerAssignmentRequest,
    ) -> WorldPatchResponse:
        with telemetry.span(
            "controller.assign",
            {"character.id": request.character_id, "controller.id": request.controller_id},
        ):
            character_id = parse_entity_id(request.character_id)
            if character_id is None or not actor.world.has_entity(character_id):
                raise HTTPException(status_code=404, detail="character does not exist")
            controller_id = parse_entity_id(request.controller_id)
            if controller_id is None or not actor.world.has_entity(controller_id):
                raise HTTPException(status_code=404, detail="controller does not exist")

            async with actor._lock:
                character = actor.world.get_entity(character_id)
                if not character.has_component(CharacterComponent):
                    raise HTTPException(status_code=400, detail="entity is not a character")
                controller = actor.world.get_entity(controller_id)
                kind = actor._controller_kind(controller_id)
                if kind == "unknown":
                    raise HTTPException(status_code=400, detail="entity is not a controller")
                current = current_controller(actor, character)
                if current is not None and current[0].id != controller_id:
                    transfer_claim(current[0], controller)
                if kind == "suspended":
                    reason = controller.get_component(SuspendedControllerComponent).reason
                    generation = actor.suspend(character_id, controller_id, reason=reason)
                else:
                    generation = actor.assign_controller(character_id, controller_id)
                    if character.has_component(SuspendedComponent):
                        character.remove_component(SuspendedComponent)

                response = WorldPatchResponse(
                    world_epoch=actor.epoch,
                    changed_entities=[serialize_entity(actor, character)],
                )

            await actor.bus.publish(
                ControllerChangedEvent(
                    **actor._event_base(
                        actor_id=str(character_id),
                        generation=generation,
                        controller_kind=kind,
                    )
                )
            )
            stream.broadcast(
                {
                    "type": "patch",
                    "data": {
                        "world_epoch": response.world_epoch,
                        "changed_entities": [str(character_id)],
                        "deleted_entities": [],
                    },
                }
            )
            return response

    def _controller_definitions_response() -> ControllerDefinitionListResponse:
        return ControllerDefinitionListResponse(
            scripts=sorted(script_names()),
            behaviors=sorted(behavior_tree_names()),
            condition_library=sorted(condition_library_names()),
            action_library=sorted(action_library_names()),
            stored=StoredControllerDefinitions(**definition_store.snapshot()),
        )

    async def _register_script_request(spec: ScriptSpec) -> ControllerDefinitionListResponse:
        try:
            async with actor._lock:
                definition_store.add_script(spec)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _controller_definitions_response()

    async def _register_behavior_request(
        spec: BehaviorTreeSpec,
    ) -> ControllerDefinitionListResponse:
        try:
            async with actor._lock:
                definition_store.add_behavior(spec)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _controller_definitions_response()

    def _list_world_generators_response() -> WorldGeneratorListResponse:
        return WorldGeneratorListResponse(
            generators=[
                WorldGeneratorInfo(
                    name=generator.name,
                    description=generator.description,
                    group=generator.group,
                    uses_seed=generator.uses_seed,
                )
                for generator in sorted(generator_registry.values(), key=lambda item: item.name)
            ]
        )

    async def _world_generation_status_response() -> WorldGenerationStatusResponse:
        if generation_job is None:
            return idle_generation_status(actor)
        return generation_job.status_response(actor)

    async def _generate_world_request(request: WorldGenerateRequest) -> WorldGenerateResponse:
        nonlocal generation_job
        if not request.confirm_reset:
            raise HTTPException(status_code=400, detail="confirm_reset must be true")
        if not plugins:
            raise HTTPException(
                status_code=409,
                detail="server was not started with a world generator registry",
            )
        if generation_job is not None and generation_job.status == "running":
            raise HTTPException(status_code=409, detail="world generation is already running")

        default_generator = "recursive" if "recursive" in generator_registry else "oneshot"
        generator_name = (request.generator or default_generator).strip()
        generator = generator_registry.get(generator_name)
        if generator is None:
            names = ", ".join(sorted(generator_registry)) or "(none)"
            raise HTTPException(
                status_code=400,
                detail=f"unknown generator {generator_name!r}; available: {names}",
            )

        options = worldgen_options or GenOptions()
        if request.max_rooms is not None:
            options = replace(options, max_rooms=request.max_rooms)
        if generator.uses_seed:
            seed = (request.seed or meta.seed or "a quiet marsh").strip() or "a quiet marsh"
        else:
            seed = generator.name
        try:
            generation_job = await start_world_generation(
                actor,
                plugins=plugins,
                generator=generator,
                seed=seed,
                options=options,
                meta=meta,
                save_path=save_path,
                save=request.save,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        stream.broadcast({"type": "snapshot", "data": serialize_world(actor, meta)})
        return generation_job.response(actor)

    async def _generate_room_request(
        request: WorldRoomGenerationRequest,
    ) -> WorldRoomGenerationResponse:
        try:
            return await generate_room_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def _generate_character_request(
        request: WorldCharacterGenerationRequest,
    ) -> WorldCharacterGenerationResponse:
        try:
            return await generate_character_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def _generate_item_request(
        request: WorldItemGenerationRequest,
    ) -> WorldItemGenerationResponse:
        try:
            return await generate_item_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def _generate_event_request(
        request: WorldEventGenerationRequest,
    ) -> WorldEventGenerationResponse:
        try:
            return await generate_event_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/admin/runtime", response_model=WorldRuntimeResponse)
    async def runtime_status() -> WorldRuntimeResponse:
        return _runtime_response()

    @app.get("/admin/memory/characters", response_model=MemoryCharactersResponse)
    async def list_memory_characters() -> MemoryCharactersResponse:
        _require_memory_store()
        return _memory_characters_response()

    @app.get(
        "/admin/memory/collections/{collection}/documents",
        response_model=MemoryDocumentsResponse,
    )
    async def list_memory_documents(collection: str) -> MemoryDocumentsResponse:
        return _memory_documents_response(collection)

    @app.post(
        "/admin/memory/collections/{collection}/documents",
        response_model=MemoryDocumentResponse,
        status_code=201,
    )
    async def create_memory_document(
        collection: str,
        request: MemoryDocumentUpdateRequest,
    ) -> MemoryDocumentResponse:
        return _memory_create_response(collection, request)

    @app.patch(
        "/admin/memory/collections/{collection}/documents/{id}",
        response_model=MemoryDocumentResponse,
    )
    async def update_memory_document(
        collection: str,
        id: str,
        request: MemoryDocumentUpdateRequest,
    ) -> MemoryDocumentResponse:
        return _memory_update_response(collection, id, request)

    @app.delete("/admin/memory/collections/{collection}/documents/{id}")
    async def delete_memory_document(collection: str, id: str) -> dict:
        return _delete_memory_document(collection, id)

    @app.post("/admin/pause", response_model=WorldRuntimeResponse)
    async def pause_world() -> WorldRuntimeResponse:
        if loop is None:
            raise HTTPException(status_code=409, detail="server runtime is not attached")
        publish = loop.pause()
        if publish is not None:
            await publish
        return _runtime_response()

    @app.post("/admin/resume", response_model=WorldRuntimeResponse)
    async def resume_world() -> WorldRuntimeResponse:
        if loop is None:
            raise HTTPException(status_code=409, detail="server runtime is not attached")
        publish = loop.resume()
        if publish is not None:
            await publish
        return _runtime_response()

    @app.get("/admin/stream")
    async def stream_status() -> dict[str, int | float]:
        return stream.stats()

    @app.post("/world/commands", response_model=CommandResponse, status_code=202)
    async def submit_command(
        request: CommandRequest,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> CommandResponse:
        _with_claim_secret(request, claim_secret)
        return await _submit_command_request(request)

    @app.delete(
        "/world/character/{id}/commands/{command_id}",
        response_model=CommandCancelResponse,
    )
    async def cancel_command(
        id: str,
        command_id: str,
        controller_id: str,
        controller_generation: int,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> CommandCancelResponse:
        return await _cancel_command_request(
            id,
            command_id,
            controller_id,
            controller_generation,
            claim_id,
            claim_secret,
        )

    @app.post("/world/controllers/web/claim", response_model=WebControllerClaimResponse)
    async def claim_web_controller(
        request: WebControllerClaimRequest,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
        player_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> WebControllerClaimResponse:
        request = _with_player_request_context(request, claim_secret, player_client_id)
        return await _claim_web_controller_request(request)

    @app.patch("/world/controllers/web/fallback", response_model=WebControllerFallbackResponse)
    async def set_web_controller_fallback(
        request: WebControllerFallbackRequest,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
        player_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> WebControllerFallbackResponse:
        request = _with_player_request_context(request, claim_secret, player_client_id)
        return await _web_controller_fallback_request(request)

    @app.post(
        "/world/controllers/web/release-controller",
        response_model=WebControllerFallbackResponse,
    )
    async def release_web_controller_to_fallback(
        request: WebControllerFallbackRequest,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
        player_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> WebControllerFallbackResponse:
        request = _with_player_request_context(request, claim_secret, player_client_id)
        return await _release_web_controller_to_fallback_request(request)

    @app.post("/world/controllers/web/release-claim", response_model=ClaimReleaseResponse)
    async def release_web_claim(
        request: WebControllerFallbackRequest,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
        player_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    ) -> ClaimReleaseResponse:
        request = _with_player_request_context(request, claim_secret, player_client_id)
        return await _release_web_claim_request(request)

    @app.patch("/admin/world", response_model=WorldPatchResponse)
    async def patch_world(request: WorldPatchRequest) -> WorldPatchResponse:
        return await _patch_world_request(request)

    @app.post("/admin/controllers/assign", response_model=WorldPatchResponse)
    async def assign_controller(
        request: ControllerAssignmentRequest,
    ) -> WorldPatchResponse:
        return await _assign_controller_request(request)

    @app.get("/admin/controllers/definitions", response_model=ControllerDefinitionListResponse)
    async def list_controller_definitions() -> ControllerDefinitionListResponse:
        return _controller_definitions_response()

    @app.post("/admin/controllers/scripts", response_model=ControllerDefinitionListResponse)
    async def register_script(request: ScriptSpec) -> ControllerDefinitionListResponse:
        return await _register_script_request(request)

    @app.post("/admin/controllers/behaviors", response_model=ControllerDefinitionListResponse)
    async def register_behavior(request: BehaviorTreeSpec) -> ControllerDefinitionListResponse:
        return await _register_behavior_request(request)

    @app.get("/admin/world/generators", response_model=WorldGeneratorListResponse)
    async def list_world_generators() -> WorldGeneratorListResponse:
        return _list_world_generators_response()

    @app.get("/admin/world/generation", response_model=WorldGenerationStatusResponse)
    async def world_generation_status() -> WorldGenerationStatusResponse:
        return await _world_generation_status_response()

    @app.post("/admin/world/generate", response_model=WorldGenerateResponse)
    async def generate_world(request: WorldGenerateRequest) -> WorldGenerateResponse:
        return await _generate_world_request(request)

    @app.post("/admin/world/generate-room", response_model=WorldRoomGenerationResponse)
    async def generate_room(request: WorldRoomGenerationRequest) -> WorldRoomGenerationResponse:
        return await _generate_room_request(request)

    @app.post(
        "/admin/world/generate-character",
        response_model=WorldCharacterGenerationResponse,
    )
    async def generate_character(
        request: WorldCharacterGenerationRequest,
    ) -> WorldCharacterGenerationResponse:
        return await _generate_character_request(request)

    @app.post("/admin/world/generate-item", response_model=WorldItemGenerationResponse)
    async def generate_item(request: WorldItemGenerationRequest) -> WorldItemGenerationResponse:
        return await _generate_item_request(request)

    @app.post("/admin/world/generate-event", response_model=WorldEventGenerationResponse)
    async def generate_event(
        request: WorldEventGenerationRequest,
    ) -> WorldEventGenerationResponse:
        return await _generate_event_request(request)

    async def _generate_image_request(
        request: WorldImageGenerationRequest,
    ) -> WorldImageGenerationResponse:
        service = _require_imagegen()
        purpose = _parse_purpose(request.purpose)
        job = await service.start(
            request.entity_id,
            purpose,
            template_name=request.template,
            extra=request.extra,
            alpha=request.alpha,
            force=request.force,
        )
        return _image_response(job)

    async def _scene_image_request(
        character_id: str,
    ) -> WorldImageGenerationResponse | None:
        # Shared by the player scene-image endpoint and the MCP camera tool. Both callers
        # guarantee imagegen is configured and the character exists; this returns None only
        # when there is no room to illustrate, which each caller renders as its own error.
        service = _require_imagegen()
        job = await request_scene_image(actor, service, character_id=character_id)
        if job is None:
            return None
        return _image_response(job)

    @app.post("/admin/world/generate-image", response_model=WorldImageGenerationResponse)
    async def generate_image(
        request: WorldImageGenerationRequest,
    ) -> WorldImageGenerationResponse:
        return await _generate_image_request(request)

    @app.get(
        "/admin/world/generate-image/{job_id}",
        response_model=WorldImageGenerationResponse,
    )
    async def image_job_status(job_id: str) -> WorldImageGenerationResponse:
        service = _require_imagegen()
        job = service.job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown image job")
        return _image_response(job)

    @app.post(
        "/admin/world/character/{character_id}/image/{purpose}",
        response_model=CharacterImageUploadResponse,
    )
    async def upload_character_image(
        character_id: str, purpose: str, request: Request
    ) -> CharacterImageUploadResponse:
        if purpose not in {"portrait", "sprite"}:
            raise HTTPException(status_code=400, detail="purpose must be portrait or sprite")

        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        extension = UPLOAD_IMAGE_TYPES.get(content_type)
        if extension is None:
            raise HTTPException(status_code=400, detail="upload must be a PNG, JPEG, or WebP image")

        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="upload body is empty")
        if len(data) > MAX_UPLOAD_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="upload image is too large")

        async with actor._lock:
            _character_entity(character_id)

        segment = SEGMENT_PORTRAITS if purpose == "portrait" else SEGMENT_SPRITES
        name = media_store.new_name(extension)
        media_store.write(segment, name, data)
        url = media_store.url_for(segment, name)

        async with actor._lock:
            character = _character_entity(character_id)
            if purpose == "portrait":
                replace_component(
                    character,
                    PortraitImageComponent(
                        url=url,
                        prompt="uploaded",
                        generated_at_epoch=actor.epoch,
                    ),
                )
            else:
                replace_component(character, SpriteImageComponent(url=url))

        return CharacterImageUploadResponse(
            world_epoch=actor.epoch,
            character_id=character_id,
            purpose=purpose,
            url=url,
            content_type=content_type,
        )

    @app.post(
        "/world/event/{record_id}/image",
        response_model=WorldImageGenerationResponse,
    )
    async def request_event_image(
        record_id: str, body: EventImageRequest | None = None
    ) -> WorldImageGenerationResponse:
        # Player-facing: events are on-request only and deduped per record by the service.
        service = _require_imagegen()
        extra = body.extra if body is not None else ""
        job = await service.start(record_id, ImagePurpose.EVENT, extra=extra)
        return _image_response(job)

    @app.post(
        "/world/character/{character_id}/scene-image",
        response_model=WorldImageGenerationResponse,
    )
    async def request_character_scene_image(
        character_id: str,
        claim_id: str | None = None,
        claim_secret: str | None = Header(default=None, alias="X-Bunnyland-Claim-Secret"),
    ) -> WorldImageGenerationResponse:
        # Player-facing: illustrate the character's current room as an on-request scene event.
        _require_imagegen()
        _require_claim_secret(
            character_id,
            claim_id=claim_id,
            claim_secret=claim_secret,
        )
        response = await _scene_image_request(character_id)
        if response is None:
            raise HTTPException(status_code=400, detail="character has no room to illustrate")
        return response

    @app.post("/admin/world/save", response_model=WorldSaveResponse)
    async def save_world_now() -> WorldSaveResponse:
        if save_path is None:
            raise HTTPException(status_code=409, detail="server was not started with --save")
        try:
            async with actor._lock:
                return save_configured_world(actor, save_path, meta=meta)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.websocket("/world/updates")
    async def world_updates(websocket: WebSocket) -> None:
        # This stream pushes the full world snapshot — the same privileged surface as
        # /world/snapshot. The production nginx config does Basic auth and then injects
        # X-Bunnyland-Admin-Secret before proxying, so the secret never rides in the query
        # string. Direct (non-proxied) clients must set the header themselves. (The /admin
        # middleware does not cover WebSocket handshakes, so this guard stays explicit.)
        try:
            _require_projection_admin(
                websocket.headers.get(ADMIN_SECRET_HEADER.lower()),
                websocket.headers.get(CLIENT_ID_HEADER.lower())
                or getattr(websocket, "query_params", {}).get("client_id"),
            )
        except HTTPException:
            await websocket.close(code=1008)  # policy violation
            return
        await websocket.accept()
        subscription = stream.subscribe()
        try:
            projection_started = time.perf_counter()
            with telemetry.span("websocket.snapshot"):
                snapshot = serialize_world(actor, meta)
            stream.record_projection_latency(time.perf_counter() - projection_started)
            await websocket.send_json(
                subscription.frame(actor, {"type": "snapshot", "data": snapshot})
            )
            while True:
                message = await next_websocket_update(actor, subscription)
                await websocket.send_json(subscription.frame(actor, message))
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

    @app.websocket("/world/character/{character_id}/updates")
    async def world_character_updates(websocket: WebSocket, character_id: str) -> None:
        # Claim secrets deliberately travel only in the first WebSocket frame.  Accepting
        # first avoids putting player state in handshake failures and keeps credentials out
        # of URLs, proxy logs, and telemetry attributes.
        await websocket.accept()
        try:
            auth = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=PLAYER_WEBSOCKET_AUTH_SECONDS,
            )
        except (TimeoutError, ValueError, TypeError, WebSocketDisconnect):
            await websocket.close(code=1008)
            return
        data = auth.get("data") if isinstance(auth, dict) else None
        if (
            not isinstance(auth, dict)
            or auth.get("type") != "authenticate"
            or not isinstance(data, dict)
            or "claim_id" not in data
            or "claim_secret" not in data
            or not isinstance(data.get("claim_id"), (str, type(None)))
            or not isinstance(data.get("claim_secret"), (str, type(None)))
        ):
            await websocket.close(code=1008)
            return
        claim_id = data["claim_id"]
        claim_secret = data["claim_secret"]
        try:
            claim_context = _require_claim_secret(
                character_id,
                claim_id=claim_id,
                claim_secret=claim_secret,
            )
            if claim_context is None and (claim_id is not None or claim_secret is not None):
                raise HTTPException(
                    status_code=403,
                    detail="unclaimed character requires null credentials",
                )
        except HTTPException:
            await websocket.close(code=1008)
            return
        require_claimed = claim_context is not None
        subscription = stream.subscribe()

        async def send_frame(frame: dict) -> bool:
            try:
                _require_claim_secret(
                    character_id,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
                    require_claimed=require_claimed,
                )
            except HTTPException:
                await websocket.close(code=1008)
                return False
            await websocket.send_json(subscription.frame(actor, frame))
            return True

        try:
            with telemetry.span("websocket.character", {"character.id": character_id}):
                if not await send_frame(
                    {
                        "type": "ready",
                        "data": {
                            "character_id": character_id,
                            "world_epoch": actor.epoch,
                        },
                    }
                ):
                    return
                while True:
                    frame = await next_player_update(actor, subscription, character_id)
                    if not await send_frame(frame):
                        return
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

    if mcp_enabled(plugins):
        mcp_app = create_bunnyland_mcp_app(
            actor=actor,
            meta=meta,
            loop=loop,
            admin_token=admin_token,
            player_client_ids=allowed_player_client_ids,
            admin_client_ids=allowed_admin_client_ids,
            save_path=save_path,
            patch_world=_patch_world_request,
            generate_world=_generate_world_request,
            generation_status=_world_generation_status_response,
            generate_room=_generate_room_request,
            generate_character=_generate_character_request,
            generate_item=_generate_item_request,
            generate_event=_generate_event_request,
            generate_image=_generate_image_request,
            scene_image=_scene_image_request if imagegen is not None else None,
            register_script=_register_script_request,
            register_behavior=_register_behavior_request,
            list_controller_definitions=_controller_definitions_response,
            fragment_providers=collect_prompt_fragments(plugins or ()),
            persona_providers=collect_persona_fragments(plugins or ()),
            worldgen_options=worldgen_options,
            claim_secrets=claim_secrets,
        )
        mcp_session_manager = getattr(mcp_app, "bunnyland_mcp_session_manager", None)
        mcp_event_bridge = getattr(mcp_app, "bunnyland_mcp_event_bridge", None)

        app.mount(
            MCP_MOUNT_PATH,
            mcp_app,
            name="mcp",
        )

    return app


__all__ = ["create_app"]
