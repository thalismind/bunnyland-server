"""Storyteller resolution rules contributed by Colony Sim."""

from ...mechanics.colonysim import PrisonerComponent
from ...mechanics.storyteller import IncidentResolutionRule


def _prisoner(world, incident, entity) -> bool:
    del world, incident
    return entity.has_component(PrisonerComponent)


RESOLUTION_RULES = (
    IncidentResolutionRule(id="prisoner-neutralized", kind="monster", resolved=_prisoner),
)

__all__ = ["RESOLUTION_RULES"]
