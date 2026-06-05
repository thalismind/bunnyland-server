"""Recursive, breadth-first world generator (spec 22).

Grows the world as a graph instead of one flat proposal:

1. Generate the root room, then its doors.
2. BFS: expand each door into a new room and generate that room's doors, until the room
   budget is reached or no door leads anywhere new.
3. Close the graph: every door still dangling is sealed, dropped, or linked back to an
   existing room (the DM decides what fits).
4. Populate each room with characters and items (the DM is reminded of all rooms first).
5. Recurse into containment: fill each character's inventory, then each container.

The LLM-never-mutates-ECS boundary holds: the world agent only proposes; this generator
validates structurally (guarding against duplicate edges) and performs every spawn/edge.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ..core.components import (
    CharacterComponent,
    ContainerComponent,
    DoorComponent,
    IdentityComponent,
    LightComponent,
    RoomComponent,
    TemperatureComponent,
)
from ..core.ecs import spawn_entity
from ..core.edges import ContainmentMode, Contains, ExitTo
from ..core.events import WorldGeneratedEvent
from .instantiate import (
    InstantiatedWorld,
    _character_components,
    _object_components,
    _wire_controller,
)
from .proposal import CharacterProposal, DoorProposal, ItemProposal, RoomNodeProposal
from .recursive_builder import WorldAgent

if TYPE_CHECKING:
    from relics import EntityId

    from ..core.world_actor import WorldActor

logger = logging.getLogger("bunnyland.worldgen")

_OPPOSITES = {
    "north": "south", "south": "north",
    "east": "west", "west": "east",
    "up": "down", "down": "up",
    "in": "out", "out": "in",
    "northeast": "southwest", "southwest": "northeast",
    "northwest": "southeast", "southeast": "northwest",
}


def _normalize_room_title(title: str) -> str:
    return " ".join(title.casefold().split())


def _opposite(direction: str) -> str:
    return _OPPOSITES.get(direction.lower(), "back")


class RecursiveWorldGenerator:
    """Builds a world graph node-by-node from a ``WorldAgent``."""

    def __init__(
        self, actor: WorldActor, builder: WorldAgent, *, max_rooms: int = 6
    ) -> None:
        self.actor = actor
        self.builder = builder
        self.max_rooms = max_rooms
        self.result = InstantiatedWorld()
        self.stats = {"rooms": 0, "sealed": 0, "dropped": 0, "linked": 0}
        self._room_specs: dict[str, RoomNodeProposal] = {}
        self._descriptions: dict[str, str] = {}
        self._room_titles: dict[str, str] = {}

    @property
    def world(self):
        return self.actor.world

    async def generate(self, seed: str) -> InstantiatedWorld:
        await self._build_rooms(seed)
        await self._populate_rooms()
        await self._fill_containment()
        await self.actor.bus.publish(
            WorldGeneratedEvent(
                event_id=uuid4().hex,
                world_epoch=self.actor.epoch,
                created_at=datetime.now(UTC),
                seed=seed,
                room_count=len(self.result.rooms),
                character_count=len(self.result.characters),
            )
        )
        logger.info("recursive worldgen: %s", self.stats)
        return self.result

    # -- phase 1-3: rooms -------------------------------------------------------------

    async def _build_rooms(self, seed: str) -> None:
        root = await asyncio.to_thread(
            self.builder.propose_room, seed, behind=None, known_rooms={}
        )
        async with self.actor._lock:
            root_key = self._spawn_room("room_0", root)
        await asyncio.sleep(0)
        frontier: deque[tuple[str, DoorProposal]] = deque(
            (root_key, door) for door in await asyncio.to_thread(self.builder.propose_doors, root)
        )
        await asyncio.sleep(0)

        counter = 1
        while frontier and len(self.result.rooms) < self.max_rooms:
            source_key, door = frontier.popleft()
            spec = await asyncio.to_thread(
                self.builder.propose_room,
                seed,
                behind=door,
                known_rooms=dict(self._room_titles),
            )
            async with self.actor._lock:
                new_key = self._spawn_room(f"room_{counter}", spec)
                counter += 1
                self._connect(source_key, new_key, door)
            await asyncio.sleep(0)
            doors = await asyncio.to_thread(self.builder.propose_doors, spec)
            frontier.extend((new_key, d) for d in doors)
            await asyncio.sleep(0)

        # Budget spent: close every remaining door.
        while frontier:
            source_key, door = frontier.popleft()
            candidates = {
                key: self._room_titles[key]
                for key in self.result.rooms
                if key != source_key and not self._connected(source_key, key)
            }
            resolution = await asyncio.to_thread(
                self.builder.resolve_dangling_door,
                door,
                room=self._room_specs[source_key],
                candidates=candidates,
            )
            async with self.actor._lock:
                self._resolve_dangling(source_key, door, candidates, resolution)
            await asyncio.sleep(0)

    def _spawn_room(self, key: str, spec: RoomNodeProposal) -> str:
        spec = self._with_unique_room_title(key, spec)
        components = [RoomComponent(title=spec.title, biome=spec.biome, indoor=spec.indoor)]
        if spec.light is not None:
            components.append(LightComponent(level=spec.light))
        if spec.celsius is not None:
            components.append(TemperatureComponent(celsius=spec.celsius))
        self.result.rooms[key] = spawn_entity(self.world, components).id
        self._room_specs[key] = spec
        self._descriptions[key] = spec.description or spec.title
        self._room_titles[key] = spec.title
        self.stats["rooms"] += 1
        return key

    def _with_unique_room_title(
        self, key: str, spec: RoomNodeProposal
    ) -> RoomNodeProposal:
        used = {_normalize_room_title(title) for title in self._room_titles.values()}
        base = spec.title.strip() or key.replace("_", " ").title()
        if _normalize_room_title(base) not in used:
            return spec.model_copy(update={"title": base})

        index = 2
        while True:
            title = f"{base} {index}"
            if _normalize_room_title(title) not in used:
                logger.warning("renaming duplicate room title %r to %r", spec.title, title)
                return spec.model_copy(update={"title": title})
            index += 1

    def _connected(self, source_key: str, dest_key: str) -> bool:
        source = self.world.get_entity(self.result.rooms[source_key])
        dest_id = self.result.rooms[dest_key]
        return any(target == dest_id for _edge, target in source.get_relationships(ExitTo))

    def _connect(self, source_key: str, dest_key: str, door: DoorProposal) -> None:
        # Relics keys edges by (type, target), so a second exit to the same room would
        # overwrite the first; skip rather than clobber.
        if self._connected(source_key, dest_key):
            return
        self.world.get_entity(self.result.rooms[source_key]).add_relationship(
            ExitTo(direction=door.direction, locked=door.locked, hidden=door.hidden),
            self.result.rooms[dest_key],
        )
        if door.bidirectional and not self._connected(dest_key, source_key):
            back = door.return_direction or _opposite(door.direction)
            self.world.get_entity(self.result.rooms[dest_key]).add_relationship(
                ExitTo(direction=back, locked=door.locked, hidden=door.hidden),
                self.result.rooms[source_key],
            )

    def _resolve_dangling(
        self,
        source_key: str,
        door: DoorProposal,
        candidates: Mapping[str, str],
        resolution,
    ) -> None:
        if resolution.action == "link" and resolution.target_room_key in candidates:
            self._connect(source_key, resolution.target_room_key, door)
            self.stats["linked"] += 1
        elif resolution.action == "seal":
            self._spawn_sealed_door(source_key, door)
            self.stats["sealed"] += 1
        else:
            self.stats["dropped"] += 1

    def _spawn_sealed_door(self, room_key: str, door: DoorProposal) -> None:
        entity = spawn_entity(
            self.world,
            [
                IdentityComponent(name=f"a sealed {door.direction} door", kind="door"),
                DoorComponent(open=False, open_on_use=False),
            ],
        )
        self.world.get_entity(self.result.rooms[room_key]).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
        )
        self.result.objects[f"door_{room_key}_{door.direction}"] = entity.id

    # -- phase 4: contents ------------------------------------------------------------

    async def _populate_rooms(self) -> None:
        char_counter = 0
        for room_key, room_id in list(self.result.rooms.items()):
            contents = await asyncio.to_thread(
                self.builder.propose_contents,
                self._room_specs[room_key],
                known_rooms=dict(self._room_titles),
            )
            async with self.actor._lock:
                for index, item in enumerate(contents.objects):
                    self._spawn_object(
                        room_id, f"{room_key}_obj{index}", item, ContainmentMode.ROOM_CONTENT
                    )
                for character in contents.characters:
                    character.key = f"char_{char_counter}"
                    char_counter += 1
                    self._spawn_character(room_id, character)
            await asyncio.sleep(0)

    def _spawn_object(
        self, container_id, key: str, item: ItemProposal, mode: ContainmentMode
    ) -> EntityId:
        entity = spawn_entity(self.world, _object_components(item))
        self.world.get_entity(container_id).add_relationship(Contains(mode=mode), entity.id)
        self.result.objects[key] = entity.id
        return entity.id

    def _spawn_character(self, room_id, character: CharacterProposal) -> None:
        entity = spawn_entity(self.world, _character_components(character))
        self.world.get_entity(room_id).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
        )
        self.result.characters[character.key] = entity.id
        _wire_controller(self.actor, entity.id, character)

    # -- phase 5: recurse into inventory and containers -------------------------------

    async def _fill_containment(self) -> None:
        for key, character_id in list(self.result.characters.items()):
            async with self.actor._lock:
                entity = self.world.get_entity(character_id)
                identity = entity.get_component(IdentityComponent)
                character = entity.get_component(CharacterComponent)
                name = identity.name
                species = character.species
            items = await asyncio.to_thread(
                self.builder.propose_inventory, name=name, species=species
            )
            async with self.actor._lock:
                for index, item in enumerate(items):
                    self._spawn_object(
                        character_id, f"{key}_inv{index}", item, ContainmentMode.INVENTORY
                    )
            await asyncio.sleep(0)

        for key, object_id in list(self.result.objects.items()):
            async with self.actor._lock:
                entity = self.world.get_entity(object_id)
                if not entity.has_component(ContainerComponent):
                    continue
                name = entity.get_component(IdentityComponent).name
            items = await asyncio.to_thread(self.builder.propose_container_contents, name=name)
            async with self.actor._lock:
                for index, item in enumerate(items):
                    self._spawn_object(
                        object_id, f"{key}_contains{index}", item, ContainmentMode.CONTAINER
                    )
            await asyncio.sleep(0)


__all__ = ["RecursiveWorldGenerator"]
