"""Storyteller resolution rules contributed by Dragon Sim."""

from bunnyland.foundation.storyteller.mechanics import IncidentResolutionRule

from .quests import QuestStateComponent


def _quest_completed(world, incident, entity) -> bool:
    del world, incident
    return entity.has_component(QuestStateComponent) and (
        entity.get_component(QuestStateComponent).status == "completed"
    )


RESOLUTION_RULES = (
    IncidentResolutionRule(id="quest-completed", kind="quest", resolved=_quest_completed),
)

__all__ = ["RESOLUTION_RULES"]
