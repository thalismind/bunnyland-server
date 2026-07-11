"""Storyteller resolution rules contributed by Colony Sim."""

from bunnyland.foundation.storyteller.mechanics import IncidentResolutionRule
from bunnyland.simpacks.colonysim.mechanics import PrisonerComponent


def _prisoner(world, incident, entity) -> bool:
    del world, incident
    return entity.has_component(PrisonerComponent)


RESOLUTION_RULES = (
    IncidentResolutionRule(id="prisoner-neutralized", kind="monster", resolved=_prisoner),
)

__all__ = ["RESOLUTION_RULES"]
