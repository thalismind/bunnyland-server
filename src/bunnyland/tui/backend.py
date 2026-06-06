"""Two ways to drive the TUI: host a world in this process, or talk to a running server.

Both expose the same tiny surface — fetch a snapshot, submit a command, claim a player —
so the app never needs to know which one it is using.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from ..core import (
    CommandCost,
    Lane,
    OnInsufficientPoints,
    WebControllerComponent,
    build_submitted_command,
    spawn_entity,
)
from ..core.ecs import parse_entity_id
from ..server.serialization import serialize_world
from .model import World


class Backend(ABC):
    """A source of world snapshots that also accepts player commands."""

    label: str = ""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def fetch_snapshot(self) -> dict: ...

    @abstractmethod
    async def submit(self, command: dict) -> bool: ...

    @abstractmethod
    async def claim(self, player_id: str, world: World) -> tuple[str, int] | None:
        """Return the controller (id, generation) the player should submit commands as."""


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

    async def start(self) -> None:
        # Imported here so the optional server/llm wiring is only pulled when hosting.
        from ..core.world_actor import WorldActor
        from ..engine import GameLoop
        from ..llm_agents import ControllerDispatch, ScriptedAgent
        from ..persistence import WorldMeta
        from ..plugins import apply_plugins, bunnyland_plugins, collect_prompt_fragments, select
        from ..prompts.builder import PromptBuilder
        from ..worldgen import GenOptions, collect_generators

        plugins = select(list(bunnyland_plugins()), None)
        self.actor = WorldActor()
        apply_plugins(plugins, self.actor)

        registry = collect_generators(plugins)
        generator = registry.get(self.generator_name)
        if generator is None:
            names = ", ".join(sorted(registry)) or "(none)"
            raise SystemExit(f"unknown generator {self.generator_name!r}; available: {names}")
        await generator.generate(self.actor, self.seed, GenOptions())
        self.meta = WorldMeta(seed=self.seed, generator=generator.name)

        builder = PromptBuilder(
            self.actor.world, fragment_providers=collect_prompt_fragments(plugins)
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

    async def claim(self, player_id: str, world: World) -> tuple[str, int] | None:
        """Hand the character to a single reusable web controller, bumping its generation
        so the offline dispatch stops driving it."""
        async with self.actor._lock:
            if self._controller is None:
                self._controller = spawn_entity(self.actor.world, [WebControllerComponent()])
            generation = self.actor.assign_controller(
                parse_entity_id(player_id), self._controller.id
            )
        return str(self._controller.id), generation


class RemoteBackend(Backend):
    """Poll a running server over HTTP for snapshots and post commands to it."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.label = f"remote · {self.base}"
        self._client = None

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

    async def submit(self, command: dict) -> bool:
        res = await self._client.post(f"{self.base}/world/commands", json=command)
        return res.is_success

    async def claim(self, player_id: str, world: World) -> tuple[str, int] | None:
        # No claim endpoint on the server; ride the controller already on the snapshot,
        # exactly as the web toon client does.
        return world.control(player_id)
