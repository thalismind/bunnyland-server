"""Storyteller resolution rules contributed by Dagger Sim."""

from ...mechanics.daggersim import PacifiedComponent
from ...mechanics.storyteller import IncidentResolutionRule


def _pacified(world, incident, entity) -> bool:
    del world, incident
    return entity.has_component(PacifiedComponent)


RESOLUTION_RULES = (
    IncidentResolutionRule(id="pacified-neutralized", kind="monster", resolved=_pacified),
)

__all__ = ["RESOLUTION_RULES"]
