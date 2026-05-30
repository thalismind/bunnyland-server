"""FastAPI app factory for web clients."""

from __future__ import annotations

from ..core.world_actor import WorldActor
from ..persistence import WorldMeta
from .models import CommandRequest, CommandResponse
from .serialization import serialize_world
from .subscriptions import EventStream

# Imported at module scope (not inside ``create_app``) so that FastAPI can resolve the
# ``websocket: WebSocket`` annotation on the route handler. Under ``from __future__ import
# annotations`` the hint is the string "WebSocket", which FastAPI looks up in this module's
# globals; a function-local import would leave it unresolvable and FastAPI would misread the
# parameter as a query field, closing every connection with a 403. Optional dependency, so
# fall back to ``None`` and raise a friendly error from ``create_app`` if it is missing.
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:  # pragma: no cover - exercised only without optional deps
    FastAPI = WebSocket = WebSocketDisconnect = CORSMiddleware = None  # type: ignore[assignment, misc]


def create_app(actor: WorldActor, meta: WorldMeta | None = None, *, title: str = "bunnyland"):
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

    @app.get("/world/events/recent")
    async def recent_events() -> dict:
        return {"events": stream.recent_messages()}

    @app.post("/world/commands", response_model=CommandResponse, status_code=202)
    async def submit_command(request: CommandRequest) -> CommandResponse:
        command = request.to_submitted(submitted_at_epoch=actor.epoch)
        await actor.submit(command)
        return CommandResponse(queued=True, command_id=command.command_id)

    @app.websocket("/world/updates")
    async def world_updates(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "snapshot", "data": serialize_world(actor, meta)})
        subscription = stream.subscribe()
        try:
            while True:
                await websocket.send_json(await subscription.queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

    return app


__all__ = ["create_app"]
