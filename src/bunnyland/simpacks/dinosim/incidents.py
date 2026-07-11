"""Storyteller incidents owned by Dino Sim."""

from functools import partial

from relics import World

from bunnyland.foundation.storyteller.mechanics import IncidentDefinition
from bunnyland.simpacks.colonysim.mechanics import ColonySimComponent
from bunnyland.simpacks.dinosim.mechanics import DinosimPolicyComponent

from ...core.components import GenerationIntentComponent


def _enabled(world: World) -> bool:
    colonies = world.query().with_all([ColonySimComponent]).execute_entities()
    policies = world.query().with_all([DinosimPolicyComponent]).execute_entities()
    return any(entity.get_component(ColonySimComponent).enabled for entity in colonies) and any(
        entity.get_component(DinosimPolicyComponent).kaiju_storyteller_incidents
        for entity in policies
    )


def _generation(kind: str, spent: float) -> GenerationIntentComponent:
    return GenerationIntentComponent(
        description=(
            f"a kaiju attack incident with total attack budget {spent:g}; "
            "spawn kaiju threats across the selected region"
        ),
        tags=("incident", "kaiju", "regional-threat"),
        wants=("kaiju-spawn", "regional-placement", "settlement-damage"),
        needs=("dinosim",),
        source_key=kind,
        entity_kind="incident",
    )


KAIJU_ATTACK = IncidentDefinition(
    id="kaiju_attack",
    cost=15.0,
    priority=40,
    eligible=_enabled,
    generation=partial(_generation, "kaiju_attack"),
)

__all__ = ["KAIJU_ATTACK"]
