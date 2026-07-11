"""Storyteller incidents owned by Barbarian Sim."""

from functools import partial

from relics import World

from bunnyland.foundation.storyteller.mechanics import IncidentDefinition
from bunnyland.simpacks.barbariansim.mechanics import BarbarianSimPolicyComponent
from bunnyland.simpacks.colonysim.mechanics import ColonySimComponent

from ...core.components import GenerationIntentComponent


def _enabled(world: World) -> bool:
    colonies = world.query().with_all([ColonySimComponent]).execute_entities()
    policies = world.query().with_all([BarbarianSimPolicyComponent]).execute_entities()
    return any(entity.get_component(ColonySimComponent).enabled for entity in colonies) and any(
        entity.get_component(BarbarianSimPolicyComponent).raid_storyteller_incidents
        for entity in policies
    )


def _generation(kind: str, spent: float) -> GenerationIntentComponent:
    return GenerationIntentComponent(
        description=(
            f"a barbarian raid incident with total attack budget {spent:g}; "
            "spawn a swarm of weak raiders led by a few officers or a warlord"
        ),
        tags=("incident", "raid", "swarm"),
        wants=("raid-swarm", "enemy-threat"),
        needs=("barbariansim",),
        source_key=kind,
        entity_kind="incident",
    )


BARBARIAN_RAID = IncidentDefinition(
    id="barbarian_raid",
    cost=12.0,
    priority=30,
    eligible=_enabled,
    generation=partial(_generation, "barbarian_raid"),
)

__all__ = ["BARBARIAN_RAID"]
