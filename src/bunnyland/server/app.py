"""FastAPI app factory for web clients."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from ..content import load_content_library
from ..core.world_actor import WorldActor
from ..persistence import WorldMeta
from .admin import save_configured_world
from .models import (
    CommandRequest,
    CommandResponse,
    WorldCharacterGenerationRequest,
    WorldCharacterGenerationResponse,
    WorldEventGenerationRequest,
    WorldEventGenerationResponse,
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
    from ..worldgen import GenOptions
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
    title: str = "bunnyland",
):
    """Create the HTTP/websocket app around a live ``WorldActor``."""

    if FastAPI is None:
        raise RuntimeError(
            "bunnyland server API requires FastAPI; install the server dependencies first"
        )

    app = FastAPI(title=title)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    stream = EventStream(actor)

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
        command = request.to_submitted(submitted_at_epoch=actor.epoch)
        await actor.submit(command)
        return CommandResponse(queued=True, command_id=command.command_id)

    @app.patch("/admin/world", response_model=WorldPatchResponse)
    async def patch_world(request: WorldPatchRequest) -> WorldPatchResponse:
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

    @app.post("/admin/world/generate-room", response_model=WorldRoomGenerationResponse)
    async def generate_room(request: WorldRoomGenerationRequest) -> WorldRoomGenerationResponse:
        try:
            return generate_room_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/admin/world/generate-character",
        response_model=WorldCharacterGenerationResponse,
    )
    async def generate_character(
        request: WorldCharacterGenerationRequest,
    ) -> WorldCharacterGenerationResponse:
        try:
            return generate_character_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/admin/world/generate-item", response_model=WorldItemGenerationResponse)
    async def generate_item(request: WorldItemGenerationRequest) -> WorldItemGenerationResponse:
        try:
            return generate_item_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/admin/world/generate-event", response_model=WorldEventGenerationResponse)
    async def generate_event(
        request: WorldEventGenerationRequest,
    ) -> WorldEventGenerationResponse:
        try:
            return generate_event_patch(actor, request, options=worldgen_options)
        except WorldPatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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

    return app


__all__ = ["create_app"]
