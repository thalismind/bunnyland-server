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

from relics import Entity, EntityId, World

from ..core.components import (
    ActionPointsComponent,
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    IdentityComponent,
    RoomComponent,
    SleepingComponent,
    SuspendedComponent,
)
from ..core.controllers import LLMControllerComponent
from ..core.ecs import container_of, parse_entity_id, reachable_ids
from ..core.edges import ControlledBy, ExitTo
from ..core.world_actor import WorldActor
from ..prompts.builder import PromptBuilder, render_prompt
from .agent import Agent
from .tools import REFERENCE_ARG_KEYS, ToolCall, command_from_tool_call

logger = logging.getLogger("bunnyland.dispatch")


def name_candidates(world: World, character: Entity) -> list[tuple[str, EntityId]]:
    """(name, id) pairs the character could be referring to: reachable entities plus the
    rooms its exits lead to. Objects/characters use their identity name; rooms use title."""
    ids = reachable_ids(world, character)
    room_id = container_of(character)
    if room_id is not None:
        for _edge, target in world.get_entity(room_id).get_relationships(ExitTo):
            ids.add(target)

    candidates: list[tuple[str, EntityId]] = []
    for entity_id in ids:
        if entity_id == character.id:
            continue
        entity = world.get_entity(entity_id)
        if entity.has_component(IdentityComponent):
            candidates.append((entity.get_component(IdentityComponent).name, entity_id))
        elif entity.has_component(RoomComponent):
            candidates.append((entity.get_component(RoomComponent).title, entity_id))
    return candidates


def resolve_reference(
    value: str, candidates: list[tuple[str, EntityId]], *, world: World
) -> str:
    """Resolve a human-readable name to an entity id (case-insensitive prefix match).

    Already-valid entity ids pass through. An exact (case-insensitive) name wins; otherwise
    the shortest candidate whose name starts with the query is chosen ("Mar" -> "marsh").
    Unresolvable values are returned unchanged so the handler rejects them observably.
    """
    parsed = parse_entity_id(value)
    if parsed is not None and world.has_entity(parsed):
        return value
    query = value.strip().lower()
    if not query:
        return value
    for name, entity_id in candidates:
        if name.lower() == query:
            return str(entity_id)
    matches = sorted(
        (nc for nc in candidates if nc[0].lower().startswith(query)),
        key=lambda nc: (len(nc[0]), nc[0].lower()),
    )
    if matches:
        return str(matches[0][1])
    return value


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

        call = self._resolve_references(character_id, call)
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

    def _resolve_references(self, character_id: EntityId, call: ToolCall) -> ToolCall:
        """Map any human-readable entity names in the call's reference args to entity ids."""
        world = self.actor.world
        character = world.get_entity(character_id)
        candidates = name_candidates(world, character)
        resolved = dict(call.arguments)
        for key in REFERENCE_ARG_KEYS:
            value = resolved.get(key)
            if isinstance(value, str):
                resolved[key] = resolve_reference(value, candidates, world=world)
        return ToolCall(name=call.name, arguments=resolved)


__all__ = ["ControllerDispatch", "Decision", "name_candidates", "resolve_reference"]
