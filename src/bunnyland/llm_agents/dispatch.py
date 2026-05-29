"""Drive LLM-controlled characters one decision at a time (spec 25.4).

Each ``run_once`` walks the active, LLM-controlled characters, builds each one's
foundation prompt, asks its agent for a single tool call, and submits the resulting
command. Decisions are logged as observable summaries (the verb and target), never hidden
chain-of-thought (spec 25.4). The engine still validates and costs everything on the next
tick — dispatch only proposes.
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace

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


def suggest_names(
    query: str, candidates: list[tuple[str, EntityId]], *, limit: int = 3
) -> list[str]:
    """Candidate names nearest an unresolvable query, for a 'did you mean...' hint.

    Prefers prefix then substring matches, then fuzzy (difflib) matches, de-duplicated and
    capped at ``limit``."""
    names = [name for name, _ in candidates]
    q = query.strip().lower()
    prefix = [n for n in names if n.lower().startswith(q)]
    substring = [n for n in names if q and q in n.lower()]
    fuzzy = difflib.get_close_matches(query, names, n=limit, cutoff=0.5)

    ordered: list[str] = []
    for name in [*prefix, *substring, *fuzzy]:
        if name not in ordered:
            ordered.append(name)
    return ordered[:limit]


def resolve_reference_args(
    world: World,
    character: Entity,
    arguments: Mapping[str, object],
    *,
    keys: frozenset[str] = REFERENCE_ARG_KEYS,
    suggestions: int = 3,
) -> tuple[dict, dict[str, list[str]]]:
    """Resolve entity-reference args to ids.

    Returns ``(resolved, unresolved)`` where ``resolved`` is a copy of ``arguments`` with
    reference keys mapped to entity ids where possible, and ``unresolved`` maps each
    reference key that did not resolve to a list of suggested names.
    """
    candidates = name_candidates(world, character)
    resolved = dict(arguments)
    unresolved: dict[str, list[str]] = {}
    for key in keys:
        value = resolved.get(key)
        if not isinstance(value, str):
            continue
        mapped = resolve_reference(value, candidates, world=world)
        resolved[key] = mapped
        parsed = parse_entity_id(mapped)
        if parsed is None or not world.has_entity(parsed):
            unresolved[key] = suggest_names(value, candidates, limit=suggestions)
    return resolved, unresolved


def did_you_mean(arguments: Mapping[str, object], unresolved: Mapping[str, list[str]]) -> str:
    """Build a 'did you mean...' message for reference args that did not resolve.

    Used for both humans (Discord reply) and LLM agents (fed back as a prompt warning), so
    the two get identical guidance."""
    parts: list[str] = []
    for key, names in unresolved.items():
        typed = arguments.get(key)
        label = key.replace("_id", "").replace("_", " ")
        if names:
            parts.append(
                f"I don't see {typed!r} ({label}) here. Did you mean: " + ", ".join(names) + "?"
            )
        else:
            parts.append(f"I don't see {typed!r} ({label}) here, and nothing similar.")
    return " ".join(parts)


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
        # character_id -> a "did you mean..." note to surface on its next prompt, so an
        # agent that named something unreachable gets the same guidance a human does.
        self._feedback: dict[str, str] = {}

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
        cid = str(character_id)

        context = self.builder.build(character_id, epoch=self.actor.epoch)
        pending = self._feedback.pop(cid, None)
        if pending is not None:
            context = replace(context, warnings=(*context.warnings, pending))
        prompt = render_prompt(context)
        call = self.agent.decide(prompt, context, character_id=cid)

        if call is None:
            logger.info("character %s decided to wait", character_id)
            return Decision(cid, None, "wait")

        # Resolve names exactly as the Discord bot does. If a reference can't be resolved,
        # don't submit a doomed command — feed the agent the same "did you mean..." hint
        # on its next turn (spec 25: tools enforce the same rules for humans and LLMs).
        character = self.actor.world.get_entity(character_id)
        resolved, unresolved = resolve_reference_args(
            self.actor.world, character, call.arguments
        )
        if unresolved:
            message = did_you_mean(call.arguments, unresolved)
            self._feedback[cid] = message
            logger.info("character %s named something unreachable: %s", character_id, message)
            return Decision(cid, call.name, f"unresolved: {message}")

        command = command_from_tool_call(
            ToolCall(name=call.name, arguments=resolved),
            character_id=cid,
            controller_id=str(controller_id),
            controller_generation=generation,
            submitted_at_epoch=self.actor.epoch,
        )
        await self.actor.submit(command)
        summary = f"{call.name} {resolved}".strip()
        logger.info("character %s chose %s", character_id, summary)
        return Decision(cid, call.name, summary)


__all__ = [
    "ControllerDispatch",
    "Decision",
    "did_you_mean",
    "name_candidates",
    "resolve_reference",
    "resolve_reference_args",
    "suggest_names",
]
