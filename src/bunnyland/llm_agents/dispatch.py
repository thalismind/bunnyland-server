"""Drive LLM-controlled characters one decision at a time (spec 25.4).

Each ``run_once`` walks the active, LLM-controlled characters, builds each one's
foundation prompt, asks its agent for a single tool call, and submits the resulting
command. Decisions are logged as observable summaries (the verb and target), never hidden
chain-of-thought (spec 25.4). The engine still validates and costs everything on the next
tick — dispatch only proposes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from relics import EntityId

from ..core.components import (
    ActionPointsComponent,
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    SleepingComponent,
    SuspendedComponent,
)
from ..core.controllers import LLMControllerComponent
from ..core.edges import ControlledBy
from ..core.world_actor import WorldActor
from ..prompts.builder import PromptBuilder, render_prompt
from .agent import Agent
from .tools import command_from_tool_call

logger = logging.getLogger("bunnyland.dispatch")


@dataclass(frozen=True)
class Decision:
    """An observable record of what an agent chose (no hidden reasoning)."""

    character_id: str
    tool: str | None
    summary: str


class ControllerDispatch:
    """Turns agent tool calls into submitted commands for LLM-controlled characters."""

    def __init__(self, actor: WorldActor, builder: PromptBuilder, agent: Agent) -> None:
        self.actor = actor
        self.builder = builder
        self.agent = agent

    async def run_once(self) -> list[Decision]:
        decisions: list[Decision] = []
        for character_id in self._actable_characters():
            decisions.append(await self._decide_for(character_id))
        return decisions

    def _actable_characters(self) -> list[EntityId]:
        query = (
            self.actor.world.query()
            .with_all([CharacterComponent])
            .with_none([SuspendedComponent, DeadComponent, DownedComponent, SleepingComponent])
        )
        actable: list[EntityId] = []
        for entity in query.execute_entities():
            if not self._has_action_point(entity):
                continue
            if self._llm_controller(entity.id) is not None:
                actable.append(entity.id)
        return actable

    @staticmethod
    def _has_action_point(entity) -> bool:
        if not entity.has_component(ActionPointsComponent):
            return False
        return entity.get_component(ActionPointsComponent).current >= 1.0

    def _llm_controller(self, character_id: EntityId) -> tuple[EntityId, int] | None:
        character = self.actor.world.get_entity(character_id)
        for edge, controller_id in character.get_relationships(ControlledBy):
            controller = self.actor.world.get_entity(controller_id)
            if controller.has_component(LLMControllerComponent):
                return controller_id, edge.generation
        return None

    async def _decide_for(self, character_id: EntityId) -> Decision:
        controller = self._llm_controller(character_id)
        assert controller is not None  # filtered in _actable_characters
        controller_id, generation = controller

        context = self.builder.build(character_id, epoch=self.actor.epoch)
        prompt = render_prompt(context)
        call = self.agent.decide(prompt, context, character_id=str(character_id))

        if call is None:
            logger.info("character %s decided to wait", character_id)
            return Decision(str(character_id), None, "wait")

        command = command_from_tool_call(
            call,
            character_id=str(character_id),
            controller_id=str(controller_id),
            controller_generation=generation,
            submitted_at_epoch=self.actor.epoch,
        )
        await self.actor.submit(command)
        summary = f"{call.name} {call.arguments}".strip()
        logger.info("character %s chose %s", character_id, summary)
        return Decision(str(character_id), call.name, summary)


__all__ = ["ControllerDispatch", "Decision"]
