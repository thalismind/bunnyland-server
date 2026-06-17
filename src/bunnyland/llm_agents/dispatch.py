"""Drive LLM-controlled characters one decision at a time (spec 25.4).

Each ``run_once`` walks the active, LLM-controlled characters, builds each one's
foundation prompt, asks its agent for a single tool call, and submits the resulting
command. Decisions are logged as observable summaries (the verb and target), never hidden
chain-of-thought (spec 25.4). The engine still validates and costs everything on the next
tick — dispatch only proposes.
"""

from __future__ import annotations

import difflib
import inspect
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from relics import Entity, EntityId, World
from relics.errors import EntityNotFoundError

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
from ..core.controllers import (
    BehaviorControllerComponent,
    LLMControllerComponent,
    ScriptedControllerComponent,
)
from ..core.ecs import container_of, contents, parse_entity_id, reachable_ids
from ..core.edges import ControlledBy, ExitTo
from ..core.world_actor import WorldActor
from ..prompts.builder import PromptBuilder, render_prompt
from .agent import CharacterAgent, ScriptedAgent
from .behavior_tree import BehaviorTree, BehaviorTreeAgent, resolve_behavior_tree
from .scripts import resolve_script
from .tools import (
    ToolCall,
    command_from_tool_call,
    reference_arg_keys,
    tool_schemas,
)

#: Controller components whose actions the engine proposes (as opposed to human/external
#: controllers like Discord/web/MCP, or the suspended no-op controller).
_AUTONOMOUS_COMPONENTS = (
    LLMControllerComponent,
    BehaviorControllerComponent,
    ScriptedControllerComponent,
)
AutonomousController = (
    LLMControllerComponent | BehaviorControllerComponent | ScriptedControllerComponent
)

logger = logging.getLogger("bunnyland.dispatch")


def name_candidates(world: World, character: Entity) -> list[tuple[str, EntityId]]:
    """(name, id) pairs the character could be referring to: reachable entities plus the
    rooms its exits lead to. Objects/characters use their identity name; rooms use title."""
    ids = reachable_ids(world, character)
    room_id = container_of(character)
    if room_id is not None:
        ids.add(room_id)
        for _edge, target in world.get_entity(room_id).get_relationships(ExitTo):
            ids.add(target)
    for entity_id in tuple(ids):
        if world.has_entity(entity_id):
            ids.update(contents(world.get_entity(entity_id)))

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


def resolve_reference(value: str, candidates: list[tuple[str, EntityId]], *, world: World) -> str:
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
    keys: frozenset[str] | None = None,
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
    for key in keys or reference_arg_keys():
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
    persona_issues: tuple[str, ...] = ()


def _tool_text(call: ToolCall) -> str:
    return " ".join(
        value.strip() for value in call.arguments.values() if isinstance(value, str)
    )


def persona_contradictions(context, call: ToolCall) -> tuple[str, ...]:
    """Detect deterministic contradictions against stable prompt persona facts."""

    text = _tool_text(call)
    if not text:
        return ()
    lowered = text.lower()
    issues: list[str] = []
    visible_names = {name.lower(): name for name in context.visible_characters}
    for pattern in (
        r"\bmy name is\s+([A-Za-z][A-Za-z0-9 _'-]{1,40})",
        r"\bcall me\s+([A-Za-z][A-Za-z0-9 _'-]{1,40})",
        r"\bi am\s+([A-Za-z][A-Za-z0-9 _'-]{1,40})",
        r"\bi'm\s+([A-Za-z][A-Za-z0-9 _'-]{1,40})",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None:
            continue
        claimed = match.group(1).strip(" .,!?:;\"'")
        claimed_key = claimed.lower()
        if claimed_key != context.name.lower() and claimed_key in visible_names:
            issues.append(
                f"name contradiction: claimed to be {visible_names[claimed_key]}"
            )
            break

    status = context.status.split(",", 1)[0].strip().lower()
    impossible_statuses = {
        "dead": ("i am dead", "i'm dead"),
        "asleep": ("i am asleep", "i'm asleep"),
        "downed": ("i am downed", "i'm downed"),
    }
    for claimed_status, phrases in impossible_statuses.items():
        if status != claimed_status and any(phrase in lowered for phrase in phrases):
            issues.append(f"impossible self-claim: claimed {claimed_status}")

    for line in context.persona:
        relationship = re.fullmatch(r"(.+) is your ([A-Za-z0-9 _'-]+)\.", line)
        if relationship is not None:
            name, relation = relationship.groups()
            name_key = name.lower()
            relation_key = relation.lower()
            if (
                f"{name_key} is not my {relation_key}" in lowered
                or f"{name_key} is not your {relation_key}" in lowered
            ):
                issues.append(
                    f"relationship contradiction: denied {name}'s {relation} status"
                )
        partner = re.fullmatch(r"You are partners with (.+)\.", line)
        if partner is not None:
            name = partner.group(1)
            name_key = name.lower()
            if f"not partners with {name_key}" in lowered:
                issues.append(f"relationship contradiction: denied partnership with {name}")
        bond = re.fullmatch(r"You (are fond of|know|fear|resent|dislike) (.+)\.", line)
        if bond is not None:
            descriptor, name = bond.groups()
            name_key = name.lower()
            descriptor_key = descriptor.lower()
            if descriptor_key == "are fond of":
                denials = (
                    f"i am not fond of {name_key}",
                    f"i'm not fond of {name_key}",
                )
            else:
                denials = (
                    f"i do not {descriptor_key} {name_key}",
                    f"i don't {descriptor_key} {name_key}",
                )
            if any(denial in lowered for denial in denials):
                issues.append(
                    f"relationship contradiction: denied bond with {name}"
                )
    return tuple(dict.fromkeys(issues))


class ControllerDispatch:
    """Turns agent tool calls into submitted commands for engine-driven characters.

    Drives every autonomous controller kind: ``llm`` (the injected ``agent``), ``behavioral``
    (a behavior tree resolved by name), and ``scripted`` (a named tool-call sequence). Human
    and external controllers (Discord/web/MCP) and the suspended no-op controller are left
    alone — the engine never proposes actions for them.
    """

    def __init__(
        self,
        actor: WorldActor,
        builder: PromptBuilder,
        agent: CharacterAgent,
        *,
        behavior_resolver: Callable[[str], BehaviorTree] = resolve_behavior_tree,
        script_resolver: Callable[[str], tuple[ToolCall, ...]] = resolve_script,
    ) -> None:
        self.actor = actor
        self.builder = builder
        self.agent = agent
        self._behavior_resolver = behavior_resolver
        self._script_resolver = script_resolver
        # character_id -> a "did you mean..." note to surface on its next prompt, so an
        # agent that named something unreachable gets the same guidance a human does.
        self._feedback: dict[str, str] = {}
        # Counts dispatch turns so a controller can act only every N ticks (the world still
        # ticks every iteration; only the agent's decisions are throttled).
        self._tick = 0
        # Behavior trees are stateless per tick, so cache one agent per tree name.
        self._behavior_agents: dict[str, BehaviorTreeAgent] = {}
        # Scripts advance across turns, so cache a replaying agent per character; rebuild it
        # if the controller's script or loop setting changes. Keyed by character id.
        self._scripted_agents: dict[str, tuple[str, bool, ScriptedAgent]] = {}

    async def run_once(self) -> list[Decision]:
        self._tick += 1
        # A live world regeneration (admin) swaps actor.world for a brand-new World object.
        # The builder captured the old world at construction; repoint it at the current one
        # so prompts are built against the live world rather than the replaced one.
        self.builder.rebind(self.actor.world)
        decisions: list[Decision] = []
        for character_id in self._actable_characters():
            # The actable list is snapshotted before the per-character awaits below; a
            # character can also be removed mid-loop by an in-place edit (admin patch or a
            # player interaction) at an await point. Skip ones already gone, and guard the
            # rest so a removal that races the prompt build/submit skips the character
            # instead of crashing the game loop.
            if not self.actor.world.has_entity(character_id):
                continue
            try:
                decisions.append(await self._decide_for(character_id))
            except EntityNotFoundError:
                logger.debug("skipping character %s removed mid-dispatch", character_id)
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
            controller = self._autonomous_controller(entity.id)
            if controller is None:
                continue
            interval = max(1, controller[2].act_every_ticks)
            if self._tick % interval == 0:
                actable.append(entity.id)
        return actable

    @staticmethod
    def _has_action_point(entity) -> bool:
        if not entity.has_component(ActionPointsComponent):
            return False
        return entity.get_component(ActionPointsComponent).current >= 1.0

    def _autonomous_controller(
        self, character_id: EntityId
    ) -> tuple[EntityId, int, AutonomousController] | None:
        """The character's engine-driven controller: ``(id, generation, component)``."""
        character = self.actor.world.get_entity(character_id)
        for edge, controller_id in character.get_relationships(ControlledBy):
            controller = self.actor.world.get_entity(controller_id)
            for component_type in _AUTONOMOUS_COMPONENTS:
                if controller.has_component(component_type):
                    component = controller.get_component(component_type)
                    return (controller_id, edge.generation, component)
        return None

    def _agent_for(
        self, character_id: str, component: AutonomousController
    ) -> tuple[CharacterAgent, str | None, str | None]:
        """Resolve the agent (and model/provider) for a controller component.

        Raises ``ValueError`` if a behavior/script name is not registered, so the caller can
        skip the character for this turn rather than crash the dispatch loop.
        """
        if isinstance(component, LLMControllerComponent):
            return self.agent, component.model, component.provider
        if isinstance(component, BehaviorControllerComponent):
            return self._behavior_agent(component.behavior_name), None, None
        return self._scripted_agent(character_id, component.script_name, component.loop), None, None

    def _behavior_agent(self, behavior_name: str) -> BehaviorTreeAgent:
        agent = self._behavior_agents.get(behavior_name)
        if agent is None:
            agent = BehaviorTreeAgent(self._behavior_resolver(behavior_name))
            self._behavior_agents[behavior_name] = agent
        return agent

    def _scripted_agent(self, character_id: str, script_name: str, loop: bool) -> ScriptedAgent:
        cached = self._scripted_agents.get(character_id)
        if cached is not None and cached[0] == script_name and cached[1] == loop:
            return cached[2]
        agent = ScriptedAgent(self._script_resolver(script_name), loop=loop)
        self._scripted_agents[character_id] = (script_name, loop, agent)
        return agent

    async def _decide_for(self, character_id: EntityId) -> Decision:
        controller = self._autonomous_controller(character_id)
        assert controller is not None  # filtered in _actable_characters
        controller_id, generation, controller_component = controller
        cid = str(character_id)

        try:
            agent, model, provider = self._agent_for(cid, controller_component)
        except ValueError as exc:
            logger.warning("character %s has an unresolvable controller: %s", character_id, exc)
            return Decision(cid, None, f"wait: {exc}")

        context = self.builder.build(character_id, epoch=self.actor.epoch)
        pending = self._feedback.pop(cid, None)
        if pending is not None:
            context = replace(context, warnings=(*context.warnings, pending))
        prompt = render_prompt(context)
        decision = agent.decide(
            prompt,
            context,
            character_id=cid,
            model=model,
            provider=provider,
            tools=tool_schemas(self.actor.action_definitions()),
        )
        call = await decision if inspect.isawaitable(decision) else decision

        if call is None:
            logger.info("character %s decided to wait", character_id)
            return Decision(cid, None, "wait")
        persona_issues = persona_contradictions(context, call)
        if persona_issues:
            logger.info(
                "character %s persona contradiction(s): %s",
                character_id,
                "; ".join(persona_issues),
            )

        # Resolve names exactly as the Discord bot does. If a reference can't be resolved,
        # don't submit a doomed command — feed the agent the same "did you mean..." hint
        # on its next turn (spec 25: tools enforce the same rules for humans and LLMs).
        character = self.actor.world.get_entity(character_id)
        resolved, unresolved = resolve_reference_args(
            self.actor.world,
            character,
            call.arguments,
            keys=reference_arg_keys(self.actor.action_definitions()),
        )
        if unresolved:
            message = did_you_mean(call.arguments, unresolved)
            self._feedback[cid] = message
            logger.info("character %s named something unreachable: %s", character_id, message)
            return Decision(cid, call.name, f"unresolved: {message}", persona_issues)

        try:
            command = command_from_tool_call(
                ToolCall(name=call.name, arguments=resolved),
                character_id=cid,
                controller_id=str(controller_id),
                controller_generation=generation,
                submitted_at_epoch=self.actor.epoch,
                definitions=self.actor.action_definitions(),
            )
        except ValueError as exc:
            message = str(exc)
            self._feedback[cid] = f"{message}. Choose one of the available tools exactly as named."
            logger.info("character %s chose an unavailable tool: %s", character_id, message)
            return Decision(cid, call.name, message, persona_issues)
        await self.actor.submit(command)
        summary = f"{call.name} {resolved}".strip()
        logger.info("character %s chose %s", character_id, summary)
        return Decision(cid, call.name, summary, persona_issues)


__all__ = [
    "ControllerDispatch",
    "Decision",
    "did_you_mean",
    "name_candidates",
    "persona_contradictions",
    "resolve_reference",
    "resolve_reference_args",
    "suggest_names",
]
