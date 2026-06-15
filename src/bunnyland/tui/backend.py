"""Two ways to drive the TUI: host a world in this process, or talk to a running server.

Both expose the same tiny surface — fetch a snapshot, submit a command, claim a player —
so the app never needs to know which one it is using.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID, uuid4

from ..core import (
    CommandCost,
    Lane,
    OnInsufficientPoints,
    SuspendedComponent,
    WebControllerComponent,
    build_submitted_command,
    spawn_entity,
)
from ..core.claim_timeout import apply_claim_timeout_settings
from ..core.ecs import parse_entity_id
from ..server.serialization import (
    serialize_character_projection,
    serialize_character_queued_commands,
    serialize_room_projection,
    serialize_world,
)
from .model import World

logger = logging.getLogger("bunnyland.tui")

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bunnyland"
CLIENT_ID_PATH = CONFIG_DIR / "client-id"


def persistent_client_id(path: Path = CLIENT_ID_PATH) -> str:
    if path.exists():
        try:
            value = path.read_text(encoding="utf-8").strip()
            return str(UUID(value))
        except ValueError:
            logger.warning("Ignoring invalid TUI client id in %s", path, exc_info=True)
        except OSError:
            logger.warning("Could not read TUI client id from %s", path, exc_info=True)

    client_id = str(uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{client_id}\n", encoding="utf-8")
    except OSError:
        logger.warning("Could not persist TUI client id to %s", path, exc_info=True)
    return client_id


class Backend(ABC):
    """A source of world snapshots that also accepts player commands."""

    label: str = ""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def fetch_snapshot(self) -> dict: ...

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        return None

    async def fetch_room_projection(self, room_id: str) -> dict | None:
        return None

    async def fetch_queued_commands(self, character_id: str) -> dict:
        return {
            "ok": True,
            "schema_version": 1,
            "world_epoch": 0,
            "character_id": character_id,
            "commands": [],
        }

    @abstractmethod
    async def submit(self, command: dict) -> bool: ...

    @abstractmethod
    async def claim(self, player_id: str, world: World) -> tuple[str, int] | None:
        """Return the controller (id, generation) the player should submit commands as."""

    async def recent_events(self) -> list[dict]:
        """Recent domain-event messages (``{"type": "event", "data": {...}}``) for clients
        that narrate perceived activity. Backends without an event feed return nothing."""
        return []


class LocalBackend(Backend):
    """Generate an offline world and tick it in-process, the TUI as a real player."""

    def __init__(
        self,
        *,
        seed: str = "a quiet marsh",
        generator: str = "apartment-demo",
        tick_seconds: float = 1.0,
        time_scale: float = 3600.0,
        autorun: bool = True,
        client_id: str | None = None,
        fallback_controller: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.seed = seed
        self.generator_name = generator
        self.tick_seconds = tick_seconds
        self.time_scale = time_scale
        self.autorun = autorun
        self.label = f"local · {generator}"
        self.actor = None
        self.meta = None
        self._loop = None
        self._task: asyncio.Task | None = None
        self._controller = None
        self._events = None
        self.client_id = client_id or persistent_client_id()
        self.fallback_controller = fallback_controller
        self.timeout_seconds = timeout_seconds

    async def start(self) -> None:
        # Imported here so the optional server/llm wiring is only pulled when hosting.
        from ..core.world_actor import WorldActor
        from ..engine import GameLoop
        from ..llm_agents import ControllerDispatch, ScriptedAgent
        from ..persistence import WorldMeta
        from ..plugins import (
            apply_plugins,
            bunnyland_plugins,
            collect_persona_fragments,
            collect_prompt_fragments,
            select,
        )
        from ..prompts.builder import PromptBuilder
        from ..server.subscriptions import EventStream
        from ..worldgen import GenOptions, collect_generators

        plugins = select(list(bunnyland_plugins()), None)
        self.actor = WorldActor()
        apply_plugins(plugins, self.actor)
        self._events = EventStream(self.actor)  # record events for clients that narrate them

        registry = collect_generators(plugins)
        generator = registry.get(self.generator_name)
        if generator is None:
            names = ", ".join(sorted(registry)) or "(none)"
            raise SystemExit(f"unknown generator {self.generator_name!r}; available: {names}")
        await generator.generate(self.actor, self.seed, GenOptions())
        self.meta = WorldMeta(seed=self.seed, generator=generator.name)

        builder = PromptBuilder(
            self.actor.world,
            fragment_providers=collect_prompt_fragments(plugins),
            persona_providers=collect_persona_fragments(plugins),
        )
        dispatch = ControllerDispatch(self.actor, builder, ScriptedAgent([]))
        self._loop = GameLoop(
            self.actor, dispatch, tick_seconds=self.tick_seconds, time_scale=self.time_scale
        )
        if self.autorun:
            self._task = asyncio.create_task(self._loop.run())

    async def close(self) -> None:
        if self._loop is not None:
            self._loop.stop()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def fetch_snapshot(self) -> dict:
        return serialize_world(self.actor, self.meta)

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        return serialize_character_projection(self.actor, character_id).model_dump(mode="json")

    async def fetch_room_projection(self, room_id: str) -> dict | None:
        return serialize_room_projection(self.actor, room_id).model_dump(mode="json")

    async def fetch_queued_commands(self, character_id: str) -> dict:
        return serialize_character_queued_commands(self.actor, character_id).model_dump(mode="json")

    async def submit(self, command: dict) -> bool:
        cost = command.get("cost") or {}
        await self.actor.submit(
            build_submitted_command(
                character_id=command["character_id"],
                controller_id=command["controller_id"],
                controller_generation=command["controller_generation"],
                command_type=command["command_type"],
                payload=command.get("payload") or {},
                cost=CommandCost(action=cost.get("action", 0), focus=cost.get("focus", 0)),
                lane=Lane(command.get("lane", "world")),
                on_insufficient_points=OnInsufficientPoints(
                    command.get("on_insufficient_points", "queue")
                ),
                submitted_at_epoch=self.actor.epoch,
            )
        )
        return True

    async def recent_events(self) -> list[dict]:
        return self._events.recent_messages() if self._events is not None else []

    async def claim(self, player_id: str, world: World) -> tuple[str, int] | None:
        """Hand the character to a single reusable web controller, bumping its generation
        so the offline dispatch stops driving it."""
        async with self.actor._lock:
            if self._controller is None:
                self._controller = spawn_entity(
                    self.actor.world,
                    [WebControllerComponent(client_id=self.client_id, label="tui")],
                )
            apply_claim_timeout_settings(
                self._controller,
                now_unix=int(time.time()),
                fallback_controller=self.fallback_controller,
                timeout_seconds=self.timeout_seconds,
                reset_activity=True,
            )
            generation = self.actor.assign_controller(
                parse_entity_id(player_id), self._controller.id
            )
            character = self.actor.world.get_entity(parse_entity_id(player_id))
            if character.has_component(SuspendedComponent):
                character.remove_component(SuspendedComponent)
        return str(self._controller.id), generation


class RemoteBackend(Backend):
    """Poll a running server over HTTP for snapshots and post commands to it."""

    def __init__(
        self,
        base_url: str,
        *,
        client_id: str | None = None,
        fallback_controller: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.label = f"remote · {self.base}"
        self._client = None
        self.client_id = client_id or persistent_client_id()
        self.fallback_controller = fallback_controller
        self.timeout_seconds = timeout_seconds

    async def start(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def fetch_snapshot(self) -> dict:
        res = await self._client.get(f"{self.base}/world/snapshot")
        res.raise_for_status()
        return res.json()

    async def fetch_character_projection(self, character_id: str) -> dict | None:
        res = await self._client.get(f"{self.base}/world/character/{character_id}")
        res.raise_for_status()
        return res.json()

    async def fetch_room_projection(self, room_id: str) -> dict | None:
        res = await self._client.get(f"{self.base}/world/room/{room_id}")
        res.raise_for_status()
        return res.json()

    async def fetch_queued_commands(self, character_id: str) -> dict:
        res = await self._client.get(
            f"{self.base}/world/character/{character_id}/commands"
        )
        res.raise_for_status()
        return res.json()

    async def submit(self, command: dict) -> bool:
        res = await self._client.post(f"{self.base}/world/commands", json=command)
        return res.is_success

    async def recent_events(self) -> list[dict]:
        res = await self._client.get(f"{self.base}/world/events/recent")
        res.raise_for_status()
        return res.json().get("events", [])

    async def claim(self, player_id: str, world: World) -> tuple[str, int] | None:
        res = await self._client.post(
            f"{self.base}/world/controllers/web/claim",
            json={
                "character_id": player_id,
                "client_id": self.client_id,
                "label": "tui",
                "fallback_controller": self.fallback_controller,
                "timeout_seconds": self.timeout_seconds,
            },
        )
        if not res.is_success:
            logger.warning(
                "Remote web controller claim failed for %s: HTTP %s %s",
                player_id,
                res.status_code,
                res.text,
            )
            return None
        data = res.json()
        return data["controller_id"], int(data["controller_generation"])
