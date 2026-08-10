"""Declarative region catalogue for the bundled Bunnyland simpacks."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.components import GenerationIntentComponent
from ..plugins.ids import (
    BARBARIANSIM,
    COLONYSIM,
    DAGGERSIM,
    DINOSIM,
    DRAGONSIM,
    GARDENSIM,
    LIFESIM,
    NEONSIM,
    NUKESIM,
    TOONSIM,
    VOIDSIM,
)
from ..worldgen.proposal import CharacterSpec, ObjectSpec, RoomSpec


@dataclass(frozen=True)
class SandboxRegionSpec:
    """One optional sandbox region owned by an already-loaded simpack."""

    plugin_id: str
    room: RoomSpec
    objects: tuple[ObjectSpec, ...] = ()
    characters: tuple[CharacterSpec, ...] = ()


def _intent(description: str, *wants: str) -> GenerationIntentComponent:
    return GenerationIntentComponent(description=description, wants=tuple(wants))


REGIONS: tuple[SandboxRegionSpec, ...] = (
    SandboxRegionSpec(
        plugin_id=COLONYSIM,
        room=RoomSpec(
            key="colony_yard",
            title="Cooperative Yard",
            biome="colony-yard",
            generation=_intent(
                "An orderly cooperative yard with a shared stockpile.",
                "bunnyland.colonysim.stockpile",
                "bunnyland.colonysim.room-stat",
            ),
        ),
        objects=(
            ObjectSpec(
                key="colony_wood_patch",
                room_key="colony_yard",
                name="a wood resource patch",
                kind="resource-node",
                portable=False,
                generation=_intent(
                    "A renewable wood patch for gathering practice.",
                    "bunnyland.colonysim.resource-node",
                ),
            ),
        ),
        characters=(
            CharacterSpec(
                key="colony_steward",
                name="Yarrow the Steward",
                room_key="colony_yard",
                controller="behavioral",
                with_memory=False,
                traits=("capable", "patient"),
                generation=_intent(
                    "A capable colony steward with practical work experience.",
                    "bunnyland.colonysim.pawn-profile",
                    "bunnyland.colonysim.work-capability",
                    "bunnyland.colonysim.work-priority",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=GARDENSIM,
        room=RoomSpec(
            key="garden_plot",
            title="Community Garden",
            biome="garden",
            generation=_intent(
                "A sunny community garden with workable soil.",
                "bunnyland.gardensim.soil",
                "bunnyland.gardensim.daily-farm-reset",
            ),
        ),
        objects=(
            ObjectSpec(
                key="garden_turnip_seeds",
                room_key="garden_plot",
                name="a packet of turnip seeds",
                kind="seed",
                generation=_intent(
                    "Turnip seeds ready to plant.",
                    "bunnyland.gardensim.seed",
                ),
            ),
            ObjectSpec(
                key="garden_maple_tree",
                room_key="garden_plot",
                name="a young maple tree",
                kind="tree",
                portable=False,
                generation=_intent(
                    "A maple tree suitable for tapping.",
                    "bunnyland.gardensim.tree",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=LIFESIM,
        room=RoomSpec(
            key="life_flat",
            title="Practice Flat",
            biome="apartment",
            indoor=True,
            generation=_intent("A modest flat for ordinary daily routines."),
        ),
        objects=(
            ObjectSpec(
                key="life_sofa",
                room_key="life_flat",
                name="a comfortable sofa",
                kind="sofa",
                portable=False,
                generation=_intent(
                    "A comfortable home sofa.",
                    "bunnyland.lifesim.home-object",
                ),
            ),
        ),
        characters=(
            CharacterSpec(
                key="life_neighbor",
                name="Clover the Neighbor",
                room_key="life_flat",
                controller="behavioral",
                with_memory=False,
                traits=("friendly", "creative"),
                generation=_intent(
                    "A creative neighbor with a home and a daily routine.",
                    "bunnyland.lifesim.profile",
                    "bunnyland.lifesim.skill-set",
                    "bunnyland.lifesim.room-claim",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=BARBARIANSIM,
        room=RoomSpec(
            key="barbarian_ring",
            title="Timber Practice Ring",
            biome="training-yard",
            generation=_intent(
                "A reinforced practice ring beyond a marked danger boundary.",
                "bunnyland.barbariansim.building",
                "bunnyland.barbariansim.danger-zone",
            ),
        ),
        objects=(
            ObjectSpec(
                key="barbarian_axe",
                room_key="barbarian_ring",
                name="a blunted practice axe",
                kind="weapon",
                generation=_intent(
                    "A durable blunted axe for sparring.",
                    "bunnyland.barbariansim.weapon",
                    "bunnyland.barbariansim.durability",
                ),
            ),
        ),
        characters=(
            CharacterSpec(
                key="barbarian_trainer",
                name="Kestrel the Trainer",
                room_key="barbarian_ring",
                controller="behavioral",
                with_memory=False,
                generation=_intent(
                    "A seasoned but non-hostile combat trainer.",
                    "bunnyland.barbariansim.combatant",
                    "bunnyland.barbariansim.stamina",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=DAGGERSIM,
        room=RoomSpec(
            key="dagger_crossing",
            title="Lantern Crossing",
            biome="old-road",
            generation=_intent(
                "An old-road travel hub beside a shallow practice dungeon.",
                "bunnyland.daggersim.travel-hub",
                "bunnyland.daggersim.dungeon",
                "bunnyland.daggersim.law-region",
            ),
        ),
        objects=(
            ObjectSpec(
                key="dagger_ingredient",
                room_key="dagger_crossing",
                name="a bundle of moonwort",
                kind="ingredient",
                generation=_intent(
                    "A common potion ingredient.",
                    "bunnyland.daggersim.ingredient",
                ),
            ),
        ),
        characters=(
            CharacterSpec(
                key="dagger_rumormonger",
                name="Moth the Rumormonger",
                room_key="dagger_crossing",
                controller="behavioral",
                with_memory=False,
                generation=_intent(
                    "A streetwise source of local rumors.",
                    "bunnyland.daggersim.rumor-source",
                    "bunnyland.daggersim.streetwise-skill",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=DINOSIM,
        room=RoomSpec(
            key="dino_paddock",
            title="Fern Paddock",
            biome="paddock",
            generation=_intent(
                "A secure fern paddock with a marked territory.",
                "bunnyland.dinosim.enclosure",
                "bunnyland.dinosim.territory",
            ),
        ),
        objects=(
            ObjectSpec(
                key="dino_fossil",
                room_key="dino_paddock",
                name="a stable fossil fragment",
                kind="fossil",
                generation=_intent(
                    "A fossil fragment ready for surveying.",
                    "bunnyland.dinosim.fossil",
                    "bunnyland.dinosim.fossil-survey",
                ),
            ),
        ),
        characters=(
            CharacterSpec(
                key="dino_juvenile",
                name="Button the Juvenile",
                room_key="dino_paddock",
                species="hypsilophodon",
                controller="behavioral",
                with_memory=False,
                generation=_intent(
                    "A calm juvenile dinosaur with ordinary creature needs.",
                    "bunnyland.dinosim.dinosaur",
                    "bunnyland.dinosim.creature-need",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=DRAGONSIM,
        room=RoomSpec(
            key="dragon_barrows",
            title="Whispering Barrows",
            biome="highland-ruin",
            generation=_intent(
                "A discoverable highland point of interest.",
                "bunnyland.dragonsim.point-of-interest",
                "bunnyland.dragonsim.discovery",
                "bunnyland.dragonsim.encounter-zone",
            ),
        ),
        objects=(
            ObjectSpec(
                key="dragon_lore_book",
                room_key="dragon_barrows",
                name="a weathered barrow almanac",
                kind="paper",
                portable=False,
                generation=_intent(
                    "A lore book describing the old barrows.",
                    "bunnyland.dragonsim.lore-book",
                ),
            ),
            ObjectSpec(
                key="dragon_artifact",
                room_key="dragon_barrows",
                name="a quiet stone artifact",
                kind="artifact",
                generation=_intent(
                    "A dormant artifact from the old barrows.",
                    "bunnyland.dragonsim.artifact",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=NEONSIM,
        room=RoomSpec(
            key="neon_arcade",
            title="Rainlight Arcade",
            biome="neon-plaza",
            indoor=True,
            generation=_intent("A public neon arcade beneath the rain."),
        ),
        objects=(
            ObjectSpec(
                key="neon_site",
                room_key="neon_arcade",
                name="a public arcade site",
                kind="site",
                portable=False,
                generation=_intent(
                    "A public cyberpunk site.",
                    "bunnyland.neonsim.cyberpunk-site",
                ),
            ),
            ObjectSpec(
                key="neon_terminal",
                room_key="neon_arcade",
                name="a practice terminal",
                kind="terminal",
                portable=False,
                generation=_intent(
                    "A resettable practice terminal.",
                    "bunnyland.neonsim.terminal",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=NUKESIM,
        room=RoomSpec(
            key="nuke_yard",
            title="Rustwater Salvage Yard",
            biome="wasteland",
            generation=_intent(
                "A monitored low-radiation scavenge site.",
                "bunnyland.nukesim.scavenge-site",
                "bunnyland.nukesim.radiation-source",
            ),
        ),
        objects=(
            ObjectSpec(
                key="nuke_poncho",
                room_key="nuke_yard",
                name="a patched protective poncho",
                kind="armor",
                generation=_intent(
                    "A patched poncho with radiation protection.",
                    "bunnyland.nukesim.rad-protection",
                ),
            ),
            ObjectSpec(
                key="nuke_junk",
                room_key="nuke_yard",
                name="a pile of salvageable junk",
                kind="junk",
                portable=False,
                generation=_intent(
                    "A small pile of contaminated junk.",
                    "bunnyland.nukesim.junk",
                ),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=TOONSIM,
        room=RoomSpec(
            key="toon_stage",
            title="Painted Backlot",
            biome="cartoon-stage",
            indoor=True,
            generation=_intent("A painted backlot for sprite movement practice."),
        ),
        objects=(
            ObjectSpec(
                key="toon_crate",
                room_key="toon_stage",
                name="a painted stage crate",
                kind="crate",
                portable=False,
                generation=_intent("A broad painted stage prop."),
            ),
        ),
    ),
    SandboxRegionSpec(
        plugin_id=VOIDSIM,
        room=RoomSpec(
            key="void_deck",
            title="Wayfarer Training Deck",
            biome="ship-module",
            indoor=True,
            generation=_intent(
                "A pressurized ship habitat module.",
                "bunnyland.voidsim.ship",
                "bunnyland.voidsim.habitat-module",
            ),
        ),
        objects=(
            ObjectSpec(
                key="void_reactor",
                room_key="void_deck",
                name="a shielded training reactor",
                kind="reactor",
                portable=False,
                generation=_intent(
                    "A low-output reactor ship system.",
                    "bunnyland.voidsim.ship-system",
                    "bunnyland.voidsim.reactor",
                ),
            ),
            ObjectSpec(
                key="void_sensor",
                room_key="void_deck",
                name="a short-range sensor console",
                kind="sensor",
                portable=False,
                generation=_intent(
                    "A short-range ship sensor.",
                    "bunnyland.voidsim.ship-system",
                    "bunnyland.voidsim.sensor",
                ),
            ),
        ),
    ),
)


__all__ = ["REGIONS", "SandboxRegionSpec"]
