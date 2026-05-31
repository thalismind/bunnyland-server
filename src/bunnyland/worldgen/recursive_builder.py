"""Builders for the recursive, graph-first world generator (spec 22).

Where ``WorldBuilder`` proposes the whole world in one shot, a ``RecursiveWorldBuilder``
proposes one piece at a time so the generator can grow the room graph breadth-first and
then populate it. ``StubRecursiveBuilder`` is deterministic (tests, offline dev);
``OllamaRecursiveBuilder`` prompts the DM node-by-node and keeps a running conversation so
earlier rooms are "remembered" when later pieces are generated.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from .defaults import DEFAULT_WORLDGEN_MODEL
from .proposal import (
    CharacterProposal,
    DanglingResolution,
    DoorProposal,
    ItemProposal,
    RoomContentsProposal,
    RoomNodeProposal,
)


class RecursiveWorldBuilder(Protocol):
    def propose_room(
        self,
        seed: str,
        *,
        behind: DoorProposal | None,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomNodeProposal: ...

    def propose_doors(
        self, room: RoomNodeProposal, *, schema_context: str = ""
    ) -> list[DoorProposal]: ...

    def resolve_dangling_door(
        self, door: DoorProposal, *, room: RoomNodeProposal, candidates: Mapping[str, str]
    ) -> DanglingResolution: ...

    def propose_contents(
        self,
        room: RoomNodeProposal,
        *,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomContentsProposal: ...

    def propose_character(
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> CharacterProposal: ...

    def propose_item(
        self,
        *,
        container_name: str,
        container_kind: str,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> ItemProposal: ...

    def propose_inventory(self, *, name: str, species: str) -> list[ItemProposal]: ...

    def propose_container_contents(self, *, name: str) -> list[ItemProposal]: ...


class StubRecursiveBuilder:
    """A fixed, deterministic builder used for tests and offline development.

    Produces a small marsh world whose root room has three doors that exercise the
    graph-closing rules: a normal two-way tunnel, a one-way slide, and a hidden vault.
    """

    ROOT_TITLE = "Mosslit Burrow"
    system_prompt = ""  # deterministic; no LLM prompt

    def propose_room(
        self,
        seed: str,
        *,
        behind: DoorProposal | None,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomNodeProposal:
        del seed, known_rooms, schema_context
        if behind is None:
            return RoomNodeProposal(
                title=self.ROOT_TITLE,
                biome="marsh",
                indoor=True,
                light=0.3,
                celsius=18.0,
                description="a damp, mossy burrow",
            )
        title = behind.beyond_hint or "Deeper Chamber"
        return RoomNodeProposal(
            title=title,
            biome="marsh",
            indoor=True,
            light=0.5,
            celsius=15.0,
            description=f"a {title.lower()}",
        )

    def propose_doors(
        self, room: RoomNodeProposal, *, schema_context: str = ""
    ) -> list[DoorProposal]:
        del schema_context
        if room.title == self.ROOT_TITLE:
            return [
                DoorProposal(direction="north", beyond_hint="North Tunnel"),
                DoorProposal(direction="down", bidirectional=False, beyond_hint="Slick Slide"),
                DoorProposal(direction="up", beyond_hint="Upper Loft"),
                DoorProposal(direction="east", hidden=True, beyond_hint="Hidden Vault"),
            ]
        if room.title == "North Tunnel":
            return [DoorProposal(direction="side", beyond_hint="Side Cave")]
        return []  # other rooms are dead-ends

    def resolve_dangling_door(
        self, door: DoorProposal, *, room: RoomNodeProposal, candidates: Mapping[str, str]
    ) -> DanglingResolution:
        del room
        if door.hidden:
            return DanglingResolution(action="seal")
        if not door.bidirectional:
            return DanglingResolution(action="drop")
        target = next(iter(candidates), None)
        if target is None:
            return DanglingResolution(action="drop")
        return DanglingResolution(action="link", target_room_key=target)

    def propose_contents(
        self,
        room: RoomNodeProposal,
        *,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomContentsProposal:
        del known_rooms, schema_context
        if room.title == self.ROOT_TITLE:
            return RoomContentsProposal(
                objects=[
                    ItemProposal(name="three berries", kind="food", nutrition=5.0, satiety=20.0),
                    ItemProposal(
                        name="a stone basin of water",
                        kind="water",
                        portable=False,
                        hydration=25.0,
                        renewable=True,
                    ),
                    ItemProposal(name="an oak chest", kind="container", portable=False, open=False),
                    ItemProposal(name="a scrap of paper", kind="paper", writable=True),
                ],
                characters=[
                    CharacterProposal(name="Juniper", controller="suspended"),
                    CharacterProposal(name="Hazel", controller="llm", llm_profile="elder"),
                ],
            )
        return RoomContentsProposal(objects=[ItemProposal(name="a smooth pebble")])

    def propose_character(
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> CharacterProposal:
        del room, known_rooms, schema_context
        return CharacterProposal(name=prompt or "Mossy Visitor", controller="suspended")

    def propose_item(
        self,
        *,
        container_name: str,
        container_kind: str,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> ItemProposal:
        del container_name, container_kind, known_rooms, schema_context
        return ItemProposal(name=prompt or "a smooth pebble")

    def propose_inventory(self, *, name: str, species: str) -> list[ItemProposal]:
        del species
        if name == "Hazel":
            return [ItemProposal(name="a hazel twig")]
        return []

    def propose_container_contents(self, *, name: str) -> list[ItemProposal]:
        if "chest" in name:
            return [ItemProposal(name="a shiny ruby")]
        return []


_SYSTEM_PROMPT = (
    "You are the DM for an asynchronous social sandbox. You build the world one piece at a "
    "time. Always reply with ONLY JSON matching the requested shape (no prose). Stay "
    "consistent with rooms you have already described."
)


class OllamaRecursiveBuilder:
    """Prompts Ollama node-by-node, keeping the conversation so earlier rooms are remembered.

    ``ollama`` is imported lazily; requires the ``llm`` extra.
    """

    #: The literal DM system prompt this builder seeds the conversation with.
    system_prompt = _SYSTEM_PROMPT

    def __init__(
        self,
        *,
        model: str = DEFAULT_WORLDGEN_MODEL,
        host: str | None = None,
        api_key: str | None = None,
    ) -> None:
        try:
            import ollama
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "OllamaRecursiveBuilder requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = ollama.Client(host=host, headers=headers) if host else ollama.Client()
        self._model = model
        self._history: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    def _ask(self, instruction: str) -> dict:  # pragma: no cover - needs network + extra
        self._history.append({"role": "user", "content": instruction})
        response = self._client.chat(
            model=self._model, format="json", messages=self._history
        )
        message = response["message"]
        self._history.append(dict(message))
        return json.loads(message["content"])

    @staticmethod
    def _with_schema_context(instruction: str, schema_context: str) -> str:
        if not schema_context:
            return instruction
        return (
            f"{instruction}\n\nLive ECS JSON schemas for this world: {schema_context}\n"
            "Use these exact component and edge names when choosing ECS-compatible "
            "details, but still reply ONLY with the requested JSON shape."
        )

    def propose_room(  # pragma: no cover - needs network + extra
        self,
        seed: str,
        *,
        behind: DoorProposal | None,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomNodeProposal:
        if behind is None:
            instruction = (
                f"Seed: {seed}. Describe the starting room as JSON with keys "
                "title, biome, indoor, light (0..1), celsius, description."
            )
        else:
            instruction = (
                f"Through the {behind.direction} door ({behind.beyond_hint!r}) lies a new room. "
                "Describe it as JSON with keys title, biome, indoor, light, celsius, description."
            )
        del known_rooms
        return RoomNodeProposal.model_validate(
            self._ask(self._with_schema_context(instruction, schema_context))
        )

    def propose_doors(  # pragma: no cover - needs network + extra
        self, room: RoomNodeProposal, *, schema_context: str = ""
    ) -> list[DoorProposal]:
        instruction = (
            f"List the doors leading out of {room.title!r} as a JSON object "
            '{"doors": [{"direction","bidirectional","return_direction","locked",'
            '"hidden","beyond_hint"}]}. Most doors are bidirectional; mark slides, '
            "cliffs, and one-way portals bidirectional=false."
        )
        data = self._ask(self._with_schema_context(instruction, schema_context))
        return [DoorProposal.model_validate(d) for d in data.get("doors", [])]

    def resolve_dangling_door(  # pragma: no cover - needs network + extra
        self, door: DoorProposal, *, room: RoomNodeProposal, candidates: Mapping[str, str]
    ) -> DanglingResolution:
        listing = "; ".join(f"{key}={title}" for key, title in candidates.items()) or "(none)"
        instruction = (
            f"The {door.direction} door out of {room.title!r} leads nowhere yet and the room "
            "budget is spent. Reply JSON {\"action\": \"seal|drop|link\", "
            '"target_room_key": <key or null>}. Prefer seal, then drop, then link to one of '
            f"these existing rooms: {listing}."
        )
        return DanglingResolution.model_validate(self._ask(instruction))

    def propose_contents(  # pragma: no cover - needs network + extra
        self,
        room: RoomNodeProposal,
        *,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomContentsProposal:
        reminder = "; ".join(f"{title}" for title in known_rooms.values())
        instruction = (
            f"Rooms so far: {reminder}. Populate {room.title!r} ({room.description}). Reply JSON "
            '{"objects":[{"name","kind","portable","nutrition","satiety","hydration",'
            '"renewable","open","writable","key_name","locked"}],'
            '"characters":[{"name","species","controller":"llm|suspended","llm_profile"}]}.'
        )
        return RoomContentsProposal.model_validate(
            self._ask(self._with_schema_context(instruction, schema_context))
        )

    def propose_character(  # pragma: no cover - needs network + extra
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> CharacterProposal:
        reminder = "; ".join(f"{title}" for title in known_rooms.values())
        instruction = (
            f"Rooms so far: {reminder}. Create one character for {room.title!r} "
            f"({room.description}). Theme/request: {prompt!r}. Reply JSON "
            '{"name","species","controller":"llm|suspended","llm_profile","traits","goals"}. '
            "Use controller=suspended unless the request explicitly asks for an LLM character."
        )
        return CharacterProposal.model_validate(
            self._ask(self._with_schema_context(instruction, schema_context))
        )

    def propose_item(  # pragma: no cover - needs network + extra
        self,
        *,
        container_name: str,
        container_kind: str,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> ItemProposal:
        reminder = "; ".join(f"{title}" for title in known_rooms.values())
        instruction = (
            f"Rooms so far: {reminder}. Create one item for {container_name!r} "
            f"(container kind: {container_kind}). Theme/request: {prompt!r}. Reply JSON "
            '{"name","kind","portable","nutrition","satiety","hydration","renewable",'
            '"open","writable","key_name","locked"}.'
        )
        return ItemProposal.model_validate(
            self._ask(self._with_schema_context(instruction, schema_context))
        )

    def propose_inventory(  # pragma: no cover - needs network + extra
        self, *, name: str, species: str
    ) -> list[ItemProposal]:
        instruction = (
            f"What is {name} (a {species}) carrying? Reply JSON "
            '{"objects":[{"name","kind","portable"}]} (may be empty).'
        )
        return [ItemProposal.model_validate(o) for o in self._ask(instruction).get("objects", [])]

    def propose_container_contents(  # pragma: no cover - needs network + extra
        self, *, name: str
    ) -> list[ItemProposal]:
        instruction = (
            f"What is inside {name}? Reply JSON "
            '{"objects":[{"name","kind","portable"}]} (may be empty).'
        )
        return [ItemProposal.model_validate(o) for o in self._ask(instruction).get("objects", [])]


__all__ = ["OllamaRecursiveBuilder", "RecursiveWorldBuilder", "StubRecursiveBuilder"]
