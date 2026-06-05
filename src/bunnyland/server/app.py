"""FastAPI app factory for web clients."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from ..content import load_content_library
from ..core.world_actor import WorldActor
from ..mcp import MCP_MOUNT_PATH, create_bunnyland_mcp_app, mcp_enabled
from ..persistence import WorldMeta
from ..plugins import collect_prompt_fragments
from ..worldgen import GenOptions, collect_generators
from .admin import idle_generation_status, save_configured_world, start_world_generation
from .models import (
    CommandRequest,
    CommandResponse,
    WorldCharacterGenerationRequest,
    WorldCharacterGenerationResponse,
    WorldEventGenerationRequest,
    WorldEventGenerationResponse,
    WorldGenerateRequest,
    WorldGenerateResponse,
    WorldGenerationStatusResponse,
    WorldGeneratorInfo,
    WorldGeneratorListResponse,
    WorldItemGenerationRequest,
    WorldItemGenerationResponse,
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
from .serialization import serialize_world
from .subscriptions import EventStream
from .worldgen import (
    generate_character_patch,
    generate_event_patch,
    generate_item_patch,
    generate_room_patch,
)

WEBSOCKET_HEARTBEAT_SECONDS = 30.0

if TYPE_CHECKING:
    from ..engine import GameLoop
    from ..plugins.model import Plugin
    from .subscriptions import EventSubscription

# Imported at module scope (not inside ``create_app``) so that FastAPI can resolve the
# ``websocket: WebSocket`` annotation on the route handler. Under ``from __future__ import
# annotations`` the hint is the string "WebSocket", which FastAPI looks up in this module's
# globals; a function-local import would leave it unresolvable and FastAPI would misread the
# parameter as a query field, closing every connection with a 403. Optional dependency, so
# fall back to ``None`` and raise a friendly error from ``create_app`` if it is missing.
try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:  # pragma: no cover - exercised only without optional deps
    FastAPI = HTTPException = WebSocket = WebSocketDisconnect = CORSMiddleware = None  # type: ignore[assignment, misc]


async def next_websocket_update(actor: WorldActor, subscription: EventSubscription) -> dict:
    try:
        return await asyncio.wait_for(
            subscription.queue.get(),
            timeout=WEBSOCKET_HEARTBEAT_SECONDS,
        )
    except TimeoutError:
        return {"type": "heartbeat", "data": {"world_epoch": actor.epoch}}


def create_app(
    actor: WorldActor,
    meta: WorldMeta | None = None,
    *,
    loop: GameLoop | None = None,
    save_path: str | Path | None = None,
    worldgen_options: GenOptions | None = None,
    plugins: list[Plugin] | None = None,
    mcp_admin_token: str | None = None,
    title: str = "bunnyland",
):
    """Create the HTTP/websocket app around a live ``WorldActor``."""

    if FastAPI is None:
        raise RuntimeError(
            "bunnyland server API requires FastAPI; install the server dependencies first"
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
            yield
        finally:
            if mcp_session_context is not None:
                await mcp_session_context.__aexit__(None, None, None)
            if mcp_event_bridge is not None:
                mcp_event_bridge.close()

    app = FastAPI(title=title, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    stream = EventStream(actor)
    meta = meta or WorldMeta()
    generator_registry = collect_generators(plugins or ())
    generation_job = None

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "world_epoch": actor.epoch}

    @app.get("/world/snapshot")
    async def world_snapshot() -> dict:
        return serialize_world(actor, meta)

    @app.get("/world/schema", response_model=WorldSchemaResponse)
    async def get_world_schema() -> WorldSchemaResponse:
        return world_schema(actor)

    @app.get("/world/library")
    async def get_world_library() -> dict:
        return load_content_library().model_dump(mode="json")

    @app.get("/world/events/recent")
    async def recent_events() -> dict:
        return {"events": stream.recent_messages()}

    def _runtime_response() -> WorldRuntimeResponse:
        if loop is None:
            raise HTTPException(status_code=409, detail="server runtime is not attached")
        return WorldRuntimeResponse(
            world_epoch=actor.epoch,
            paused=loop.paused,
            running=loop.running,
        )

    async def _submit_command_request(request: CommandRequest) -> CommandResponse:
        command = request.to_submitted(submitted_at_epoch=actor.epoch)
        await actor.submit(command)
        return CommandResponse(queued=True, command_id=command.command_id)

    async def _patch_world_request(request: WorldPatchRequest) -> WorldPatchResponse:
        try:
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

    def _list_world_generators_response() -> WorldGeneratorListResponse:
        return WorldGeneratorListResponse(
            generators=[
                WorldGeneratorInfo(
                    name=generator.name,
                    description=generator.description,
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

    def _generate_room_request(
        request: WorldRoomGenerationRequest,
    ) -> WorldRoomGenerationResponse:
        try:
            return generate_room_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _generate_character_request(
        request: WorldCharacterGenerationRequest,
    ) -> WorldCharacterGenerationResponse:
        try:
            return generate_character_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _generate_item_request(
        request: WorldItemGenerationRequest,
    ) -> WorldItemGenerationResponse:
        try:
            return generate_item_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _generate_event_request(
        request: WorldEventGenerationRequest,
    ) -> WorldEventGenerationResponse:
        try:
            return generate_event_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/admin/runtime", response_model=WorldRuntimeResponse)
    async def runtime_status() -> WorldRuntimeResponse:
        return _runtime_response()

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

    @app.post("/world/commands", response_model=CommandResponse, status_code=202)
    async def submit_command(request: CommandRequest) -> CommandResponse:
        return await _submit_command_request(request)

    @app.patch("/admin/world", response_model=WorldPatchResponse)
    async def patch_world(request: WorldPatchRequest) -> WorldPatchResponse:
        return await _patch_world_request(request)

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
        return _generate_room_request(request)

    @app.post(
        "/admin/world/generate-character",
        response_model=WorldCharacterGenerationResponse,
    )
    async def generate_character(
        request: WorldCharacterGenerationRequest,
    ) -> WorldCharacterGenerationResponse:
        return _generate_character_request(request)

    @app.post("/admin/world/generate-item", response_model=WorldItemGenerationResponse)
    async def generate_item(request: WorldItemGenerationRequest) -> WorldItemGenerationResponse:
        return _generate_item_request(request)

    @app.post("/admin/world/generate-event", response_model=WorldEventGenerationResponse)
    async def generate_event(
        request: WorldEventGenerationRequest,
    ) -> WorldEventGenerationResponse:
        return _generate_event_request(request)

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
        await websocket.accept()
        subscription = stream.subscribe()
        try:
            await websocket.send_json({"type": "snapshot", "data": serialize_world(actor, meta)})
            while True:
                await websocket.send_json(await next_websocket_update(actor, subscription))
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

    if mcp_enabled(plugins):
        mcp_app = create_bunnyland_mcp_app(
            actor=actor,
            meta=meta,
            loop=loop,
            admin_token=mcp_admin_token,
            patch_world=_patch_world_request,
            generate_world=_generate_world_request,
            generation_status=_world_generation_status_response,
            generate_room=_generate_room_request,
            generate_character=_generate_character_request,
            generate_item=_generate_item_request,
            generate_event=_generate_event_request,
            fragment_providers=collect_prompt_fragments(plugins or ()),
            worldgen_options=worldgen_options,
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
