"""Deterministic plugin-aware sandbox world generation."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ..core.components import GenerationIntentComponent, WorldInfoComponent
from ..core.ecs import replace_component
from ..core.generation import GenerationDelta, GenerationRequest
from ..worldgen.generators import GenOptions
from ..worldgen.instantiate import InstantiatedWorld, instantiate
from ..worldgen.proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal
from .mechanics import (
    AFTER_DARK_SCOPE,
    AfterDarkEntranceComponent,
    AfterDarkExitComponent,
    AfterDarkPassage,
)
from .regions import REGIONS, SandboxRegionSpec

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor

ENTRANCE_CAPABILITY = "bunnyland.sandbox.after-dark-entrance"
EXIT_CAPABILITY = "bunnyland.sandbox.after-dark-exit"
CAPABILITIES = (ENTRANCE_CAPABILITY, EXIT_CAPABILITY)


class SandboxGenerationEnricher:
    """Compile sandbox portal markers through the normal enrichment pipeline."""

    capabilities = CAPABILITIES

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        wanted = set(request.capabilities)
        components = []
        satisfied = []
        if ENTRANCE_CAPABILITY in wanted:
            components.append(AfterDarkEntranceComponent())
            satisfied.append(ENTRANCE_CAPABILITY)
        if EXIT_CAPABILITY in wanted:
            components.append(AfterDarkExitComponent())
            satisfied.append(EXIT_CAPABILITY)
        return GenerationDelta(components=tuple(components), satisfies=tuple(satisfied))


GENERATION_ENRICHER = SandboxGenerationEnricher()


def _intent(description: str, *wants: str) -> GenerationIntentComponent:
    return GenerationIntentComponent(description=description, wants=tuple(wants))


def _enabled_regions(actor: WorldActor) -> tuple[SandboxRegionSpec, ...]:
    registry = actor.plugins
    if registry is None:
        return ()
    return tuple(region for region in REGIONS if registry.enabled(region.plugin_id))


def _base_rooms() -> list[RoomSpec]:
    return [
        RoomSpec(
            key="arrival",
            title="Crossroads Arrival",
            biome="crossroads",
            indoor=True,
            light=0.8,
            celsius=21.0,
            generation=_intent(
                "A welcoming arrival hall with clear signs leading toward the Commons."
            ),
        ),
        RoomSpec(
            key="commons",
            title="Crossroads Commons",
            biome="commons",
            light=0.85,
            celsius=20.0,
            generation=_intent(
                "A shared public commons connecting the installed simpack regions."
            ),
        ),
        RoomSpec(
            key="after_dark_foyer",
            title="After Dark Foyer",
            biome="after-dark",
            indoor=True,
            light=0.35,
            celsius=21.0,
            generation=_intent(
                "The quiet foyer of an optional adults-only district with explicit boundaries."
            ),
        ),
        RoomSpec(
            key="after_dark_lounge",
            title="After Dark Lounge",
            biome="after-dark",
            indoor=True,
            light=0.25,
            celsius=22.0,
            generation=_intent(
                "A private lounge where all interaction boundaries remain independently enforced."
            ),
        ),
    ]


def _base_objects(regions: tuple[SandboxRegionSpec, ...]) -> list[ObjectSpec]:
    region_names = ", ".join(region.room.title for region in regions) or "none"
    return [
        ObjectSpec(
            key="arrival_guide",
            room_key="arrival",
            name="the Crossroads arrival guide",
            kind="paper",
            portable=False,
            generation=_intent(
                "Claim a New Arrival, look around, and travel east to Crossroads Commons. "
                "Ordinary regions appear only when their simpack plugin is loaded."
            ),
        ),
        ObjectSpec(
            key="commons_map",
            room_key="commons",
            name="the Commons region map",
            kind="paper",
            portable=False,
            generation=_intent(f"Installed sandbox regions: {region_names}."),
        ),
        ObjectSpec(
            key="after_dark_entrance",
            room_key="commons",
            name="the After Dark entrance",
            kind="door",
            portable=False,
            generation=_intent(
                "Optional adults-only access. Accept the warning, then use enter-after-dark. "
                "Entry consent does not grant consent for any separate interaction.",
                ENTRANCE_CAPABILITY,
            ),
        ),
        ObjectSpec(
            key="after_dark_exit",
            room_key="after_dark_foyer",
            name="the exit to Crossroads Commons",
            kind="door",
            portable=False,
            generation=_intent(
                "An unconditional exit from After Dark to the public Commons.",
                EXIT_CAPABILITY,
            ),
        ),
        ObjectSpec(
            key="after_dark_boundaries",
            room_key="after_dark_foyer",
            name="the After Dark boundaries notice",
            kind="paper",
            portable=False,
            generation=_intent(
                "Entry is optional and revocable. Every adult interaction retains its own "
                "policy and participant-consent checks. Use leave-after-dark at any time."
            ),
        ),
    ]


def _arrivals() -> list[CharacterSpec]:
    return [
        CharacterSpec(
            key=f"new_arrival_{index}",
            name=f"New Arrival {index}",
            room_key="arrival",
            controller="suspended",
            with_memory=True,
            traits=("curious",),
            goals=("explore Crossroads Commons",),
            generation=_intent("A ready-to-play New Arrival bunny."),
        )
        for index in range(1, 5)
    ]


def _proposal(seed: str, regions: tuple[SandboxRegionSpec, ...]) -> WorldProposal:
    rooms = _base_rooms()
    objects = [*_base_objects(regions)]
    characters = [*_arrivals()]
    exits = [
        ExitSpec(from_key="arrival", direction="east", to_key="commons"),
        ExitSpec(from_key="commons", direction="west", to_key="arrival"),
        ExitSpec(from_key="after_dark_foyer", direction="in", to_key="after_dark_lounge"),
        ExitSpec(from_key="after_dark_lounge", direction="out", to_key="after_dark_foyer"),
    ]
    for region in regions:
        rooms.append(region.room)
        objects.extend(region.objects)
        characters.extend(region.characters)
        exits.extend(
            (
                ExitSpec(
                    from_key="commons",
                    direction=region.room.key,
                    to_key=region.room.key,
                ),
                ExitSpec(
                    from_key=region.room.key,
                    direction="commons",
                    to_key="commons",
                ),
            )
        )
    return WorldProposal(
        seed=seed,
        rooms=rooms,
        exits=exits,
        objects=objects,
        characters=characters,
    )


async def sandbox_generator(
    actor: WorldActor,
    seed: str,
    options: GenOptions,
) -> InstantiatedWorld:
    """Build Crossroads and enrich one region for each enabled bundled simpack."""

    del options
    regions = _enabled_regions(actor)
    result = await instantiate(actor, _proposal(seed, regions))
    async with actor._lock:
        entrance = actor.world.get_entity(result.objects["after_dark_entrance"])
        entrance.add_relationship(
            AfterDarkPassage(),
            result.rooms["after_dark_foyer"],
        )
        exit_marker = actor.world.get_entity(result.objects["after_dark_exit"])
        exit_marker.add_relationship(AfterDarkPassage(), result.rooms["commons"])

        info_entity = next(
            actor.world.query().with_all([WorldInfoComponent]).execute_entities()
        )
        info = info_entity.get_component(WorldInfoComponent)
        region_names = ", ".join(region.room.title for region in regions) or "no simpack regions"
        replace_component(
            info_entity,
            replace(
                info,
                title="Bunnyland Crossroads Sandbox",
                description=(
                    f"Loaded simpack regions: {region_names}. After Dark is optional and "
                    "requires explicit in-world acknowledgement and entry commands."
                ),
                content_flags=info.content_flags | {AFTER_DARK_SCOPE},
            ),
        )
    return result


__all__ = [
    "CAPABILITIES",
    "ENTRANCE_CAPABILITY",
    "EXIT_CAPABILITY",
    "GENERATION_ENRICHER",
    "SandboxGenerationEnricher",
    "sandbox_generator",
]
