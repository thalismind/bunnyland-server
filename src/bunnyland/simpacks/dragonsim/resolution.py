"""Storyteller resolution rules contributed by Dragon Sim."""

from ...mechanics.storyteller import IncidentResolutionRule
from .quests import GeneratedQuestComponent, QuestComponent


def _quest_completed(world, incident, entity) -> bool:
    del world, incident
    for component_type in (QuestComponent, GeneratedQuestComponent):
        if entity.has_component(component_type):
            return entity.get_component(component_type).status == "completed"
    return False


RESOLUTION_RULES = (
    IncidentResolutionRule(id="quest-completed", kind="quest", resolved=_quest_completed),
)

__all__ = ["RESOLUTION_RULES"]
