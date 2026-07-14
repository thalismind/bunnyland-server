"""Storyteller resolution rules contributed by Dino Sim."""

from bunnyland.foundation.storyteller.mechanics import IncidentResolutionRule
from bunnyland.simpacks.dinosim.mechanics import (
    ApexPredatorComponent,
    CompanionOf,
    EnclosureComponent,
    GateComponent,
    KaijuComponent,
    SettlementDamageComponent,
    TamingComponent,
)

from ...core.ecs import container_of


def _creature_neutralized(world, incident, entity) -> bool:
    del incident
    if entity.get_relationships(CompanionOf):
        return True
    if entity.has_component(TamingComponent) and entity.get_component(TamingComponent).tamed:
        return True
    container_id = container_of(entity)
    if container_id is not None and world.has_entity(container_id):
        container = world.get_entity(container_id)
        if container.has_component(EnclosureComponent):
            return (
                not container.has_component(GateComponent)
                or container.get_component(GateComponent).locked
            )
    if entity.has_component(KaijuComponent):
        return entity.get_component(KaijuComponent).threat_level <= 0
    if entity.has_component(ApexPredatorComponent):
        return entity.get_component(ApexPredatorComponent).threat_level <= 0
    return False


def _damage_repaired(world, incident, entity) -> bool:
    del world, incident
    if not entity.has_component(SettlementDamageComponent):
        return True
    damage = entity.get_component(SettlementDamageComponent)
    return damage.repaired or damage.severity <= 0


RESOLUTION_RULES = (
    IncidentResolutionRule(
        id="creature-neutralized", kind="monster", resolved=_creature_neutralized
    ),
    IncidentResolutionRule(id="settlement-repaired", kind="damage", resolved=_damage_repaired),
)

__all__ = ["RESOLUTION_RULES"]
