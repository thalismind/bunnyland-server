"""Builders for the recursive, graph-first world generator (spec 22).

A ``WorldAgent`` proposes one piece at a time so the generator can grow the room graph
breadth-first and then populate it. ``StubWorldAgent`` is deterministic (tests, offline
dev); ``OllamaWorldAgent`` prompts the DM node-by-node and keeps a running conversation so
earlier rooms are "remembered" when later pieces are generated.

Every proposal method is a coroutine: LLM calls must not block the asyncio event loop the
server runs on, so they go through async clients (or, where no async client exists, a
worker thread).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from .. import telemetry
from ..llm_agents.agent import (
    _llm_request_attrs,
    _ollama_usage,
    _openrouter_usage,
    _record_llm_usage,
)
from .defaults import DEFAULT_WORLDGEN_MODEL
from .proposal import (
    CharacterProposal,
    DanglingResolution,
    DoorProposal,
    ItemProposal,
    RoomContentsProposal,
    RoomNodeProposal,
    StoryEventProposal,
)


class WorldAgent(Protocol):
    """DM/world-builder role.

    The core proposal methods are room, doors, contents, character, and item proposals.
    The additional methods below cover the current recursive generator's graph-closing and
    containment recursion phases. Every method is async so implementations can issue LLM
    calls without blocking the event loop.
    """

    async def propose_room(
        self,
        seed: str,
        *,
        behind: DoorProposal | None,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomNodeProposal: ...

    async def propose_doors(
        self, room: RoomNodeProposal, *, schema_context: str = ""
    ) -> list[DoorProposal]: ...

    async def resolve_dangling_door(
        self, door: DoorProposal, *, room: RoomNodeProposal, candidates: Mapping[str, str]
    ) -> DanglingResolution: ...

    async def propose_contents(
        self,
        room: RoomNodeProposal,
        *,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomContentsProposal: ...

    async def propose_character(
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> CharacterProposal: ...

    async def propose_item(
        self,
        *,
        container_name: str,
        container_kind: str,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> ItemProposal: ...

    async def propose_event(
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> StoryEventProposal: ...

    async def propose_inventory(self, *, name: str, species: str) -> list[ItemProposal]: ...

    async def propose_container_contents(self, *, name: str) -> list[ItemProposal]: ...


class StubWorldAgent:
    """A fixed, deterministic builder used for tests and offline development.

    Produces a small marsh world whose root room has three doors that exercise the
    graph-closing rules: a normal two-way tunnel, a one-way slide, and a hidden vault.
    """

    ROOT_TITLE = "Mosslit Burrow"
    system_prompt = ""  # deterministic; no LLM prompt

    async def propose_room(
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

    async def propose_doors(
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

    async def resolve_dangling_door(
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

    async def propose_contents(
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

    async def propose_character(
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> CharacterProposal:
        del room, known_rooms, schema_context
        return CharacterProposal(name=prompt or "Mossy Visitor", controller="suspended")

    async def propose_item(
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

    async def propose_event(
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> StoryEventProposal:
        del room, known_rooms, schema_context
        title = prompt or "A sudden rustle"
        return StoryEventProposal(
            title=title,
            kind="story_event",
            summary=f"{title} draws attention in the room.",
            severity=1.0,
            budget_spent=1.0,
            tags=("generated",),
            stimulus_intensity=1.0,
            objects=[ItemProposal(name="a dropped clue", kind="item")],
        )

    async def propose_inventory(self, *, name: str, species: str) -> list[ItemProposal]:
        del species
        if name == "Hazel":
            return [ItemProposal(name="a hazel twig")]
        return []

    async def propose_container_contents(self, *, name: str) -> list[ItemProposal]:
        if "chest" in name:
            return [ItemProposal(name="a shiny ruby")]
        return []


_SYSTEM_PROMPT = (
    "You are the DM for an asynchronous social sandbox. You build the world one piece at a "
    "time. Always reply with ONLY JSON matching the requested shape (no prose). Stay "
    "consistent with rooms you have already described."
)


class OllamaWorldAgent:
    """Prompts Ollama node-by-node, keeping the conversation so earlier rooms are remembered.

    ``ollama`` is imported lazily; requires the ``llm`` extra. Uses ``ollama.AsyncClient`` so
    the per-node ``chat`` calls await on the event loop instead of blocking it.
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
        except ImportError as exc:
            raise RuntimeError(
                "OllamaWorldAgent requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        client_cls = ollama.AsyncClient
        self._client = client_cls(host=host, headers=headers) if host else client_cls()
        self._model = model
        self._history: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    async def _ask(self, instruction: str) -> dict:
        self._history.append({"role": "user", "content": instruction})
        attrs = {"provider": "ollama", "model": self._model}
        with telemetry.record_duration(
            telemetry.record_worldgen_request, attrs
        ), telemetry.span(
            "worldgen.llm.request",
            {
                **attrs,
                **_llm_request_attrs(
                    "worldgen",
                    self._model,
                    self._history,
                    None,
                    system_prompt=_SYSTEM_PROMPT,
                ),
                "instruction.chars": len(instruction),
            },
        ) as request_span:
            response = await self._client.chat(
                model=self._model, format="json", messages=self._history
            )
            _annotate_worldgen_usage(request_span, "ollama", self._model, _ollama_usage(response))
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

    async def propose_room(
        self,
        seed: str,
        *,
        behind: DoorProposal | None,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> RoomNodeProposal:
        existing = "; ".join(known_rooms.values()) or "(none)"
        if behind is None:
            instruction = (
                f"Seed: {seed}. Describe the starting room as JSON with keys "
                "title, biome, indoor, light (0..1), celsius, description."
            )
        else:
            instruction = (
                f"Through the {behind.direction} door ({behind.beyond_hint!r}) lies a new room. "
                f"Existing room titles: {existing}. Choose a title that is not already used. "
                "Describe it as JSON with keys title, biome, indoor, light, celsius, description."
            )
        return RoomNodeProposal.model_validate(
            await self._ask(self._with_schema_context(instruction, schema_context))
        )

    async def propose_doors(
        self, room: RoomNodeProposal, *, schema_context: str = ""
    ) -> list[DoorProposal]:
        instruction = (
            f"List the doors leading out of {room.title!r} as a JSON object "
            '{"doors": [{"direction","bidirectional","return_direction","locked",'
            '"hidden","beyond_hint"}]}. Most doors are bidirectional; mark slides, '
            "cliffs, and one-way portals bidirectional=false."
        )
        data = await self._ask(self._with_schema_context(instruction, schema_context))
        return [DoorProposal.model_validate(d) for d in data.get("doors", [])]

    async def resolve_dangling_door(
        self, door: DoorProposal, *, room: RoomNodeProposal, candidates: Mapping[str, str]
    ) -> DanglingResolution:
        listing = "; ".join(f"{key}={title}" for key, title in candidates.items()) or "(none)"
        instruction = (
            f"The {door.direction} door out of {room.title!r} leads nowhere yet and the room "
            "budget is spent. Reply JSON {\"action\": \"seal|drop|link\", "
            '"target_room_key": <key or null>}. Prefer seal, then drop, then link to one of '
            f"these existing rooms: {listing}."
        )
        return DanglingResolution.model_validate(await self._ask(instruction))

    async def propose_contents(
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
            await self._ask(self._with_schema_context(instruction, schema_context))
        )

    async def propose_character(
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
            await self._ask(self._with_schema_context(instruction, schema_context))
        )

    async def propose_item(
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
            await self._ask(self._with_schema_context(instruction, schema_context))
        )

    async def propose_event(
        self,
        room: RoomNodeProposal,
        *,
        prompt: str,
        known_rooms: Mapping[str, str],
        schema_context: str = "",
    ) -> StoryEventProposal:
        reminder = "; ".join(f"{title}" for title in known_rooms.values())
        instruction = (
            f"Rooms so far: {reminder}. Create one plausible event, incident, or encounter "
            f"that could happen in {room.title!r} ({room.description}). Theme/request: "
            f"{prompt!r}. Reply JSON "
            '{"title","kind","summary","severity","budget_spent","tags","stimulus_type",'
            '"stimulus_intensity","objects":[{"name","kind","portable","nutrition",'
            '"satiety","hydration","renewable","open","writable","key_name","locked"}],'
            '"characters":[{"name","species","controller":"llm|suspended","llm_profile",'
            '"traits","goals"}]}. Keep objects and characters empty unless the event needs '
            "new physical entities. Use controller=suspended unless the request explicitly "
            "asks for an LLM character."
        )
        return StoryEventProposal.model_validate(
            await self._ask(self._with_schema_context(instruction, schema_context))
        )

    async def propose_inventory(
        self, *, name: str, species: str
    ) -> list[ItemProposal]:
        instruction = (
            f"What is {name} (a {species}) carrying? Reply JSON "
            '{"objects":[{"name","kind","portable"}]} (may be empty).'
        )
        data = await self._ask(instruction)
        return [ItemProposal.model_validate(o) for o in data.get("objects", [])]

    async def propose_container_contents(
        self, *, name: str
    ) -> list[ItemProposal]:
        instruction = (
            f"What is inside {name}? Reply JSON "
            '{"objects":[{"name","kind","portable"}]} (may be empty).'
        )
        data = await self._ask(instruction)
        return [ItemProposal.model_validate(o) for o in data.get("objects", [])]


class OpenRouterWorldAgent(OllamaWorldAgent):
    """Prompts OpenRouter node-by-node on the same ``WorldAgent`` proposal surface.

    Uses the OpenRouter SDK's async chat call so world generation does not block the event
    loop.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_WORLDGEN_MODEL,
        api_key: str | None = None,
        server_url: str | None = None,
    ) -> None:
        try:
            from openrouter import OpenRouter
        except ImportError as exc:
            raise RuntimeError(
                "OpenRouterWorldAgent requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        kwargs = {"api_key": api_key}
        if server_url:
            kwargs["server_url"] = server_url
        self._client = OpenRouter(**kwargs)
        self._model = model
        self._history: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    async def _ask(self, instruction: str) -> dict:
        self._history.append({"role": "user", "content": instruction})
        attrs = {"provider": "openrouter", "model": self._model}
        with telemetry.record_duration(
            telemetry.record_worldgen_request, attrs
        ), telemetry.span(
            "worldgen.llm.request",
            {
                **attrs,
                **_llm_request_attrs(
                    "worldgen",
                    self._model,
                    self._history,
                    None,
                    system_prompt=_SYSTEM_PROMPT,
                ),
                "instruction.chars": len(instruction),
            },
        ) as request_span:
            response = await self._client.chat.send_async(
                model=self._model,
                messages=self._history,
                response_format={"type": "json_object"},
            )
            _annotate_worldgen_usage(
                request_span, "openrouter", self._model, _openrouter_usage(response)
            )
        message = response.choices[0].message
        self._history.append(_message_to_history(message))
        content = getattr(message, "content", None) or "{}"
        return json.loads(content)


def _annotate_worldgen_usage(
    request_span, provider: str, model: str, usage
) -> None:
    """Record a worldgen LLM call's token counts to both the metric and the active span."""
    _record_llm_usage(provider, model, usage)
    request_span.set_attribute("llm.tokens.prompt", usage.prompt_tokens)
    request_span.set_attribute("llm.tokens.completion", usage.completion_tokens)
    request_span.set_attribute("llm.tokens.total", usage.total_tokens)
    if usage.cost:
        request_span.set_attribute("llm.cost", usage.cost)


def _message_to_history(message) -> dict:
    if hasattr(message, "model_dump"):
        return message.model_dump(mode="json", exclude_none=True)
    result = {"role": getattr(message, "role", "assistant")}
    content = getattr(message, "content", None)
    if content is not None:
        result["content"] = content
    return result


RecursiveWorldBuilder = WorldAgent
StubRecursiveBuilder = StubWorldAgent
OllamaRecursiveBuilder = OllamaWorldAgent


__all__ = [
    "OllamaRecursiveBuilder",
    "OllamaWorldAgent",
    "OpenRouterWorldAgent",
    "RecursiveWorldBuilder",
    "StubRecursiveBuilder",
    "StubWorldAgent",
    "WorldAgent",
]
