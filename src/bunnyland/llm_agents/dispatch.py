"""Drive LLM-controlled characters one decision at a time (spec 25.4).

Each ``run_once`` walks the active, LLM-controlled characters, builds each one's
foundation prompt, asks its agent for a single tool call, and submits the resulting
command. Decisions are logged as observable summaries (the verb and target), never hidden
chain-of-thought (spec 25.4). The engine still validates and costs everything on the next
tick — dispatch only proposes.
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from relics import Entity, EntityId, World
from relics.errors import EntityNotFoundError

from .. import telemetry
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

logger = logging.getLogger("bunnyland.dispatch")

ControllerAgentFactory = Callable[
    ["ControllerDispatch", str, object],
    tuple[CharacterAgent, str | None, str | None],
]


def _llm_agent_factory(
    dispatch: ControllerDispatch, _character_id: str, component: object
) -> tuple[CharacterAgent, str | None, str | None]:
    controller = component
    assert isinstance(controller, LLMControllerComponent)
    return dispatch.agent, controller.model, controller.provider


def _behavior_agent_factory(
    dispatch: ControllerDispatch, _character_id: str, component: object
) -> tuple[CharacterAgent, str | None, str | None]:
    controller = component
    assert isinstance(controller, BehaviorControllerComponent)
    return dispatch._behavior_agent(controller.behavior_name), None, None


def _scripted_agent_factory(
    dispatch: ControllerDispatch, character_id: str, component: object
) -> tuple[CharacterAgent, str | None, str | None]:
    controller = component
    assert isinstance(controller, ScriptedControllerComponent)
    return (
        dispatch._scripted_agent(character_id, controller.script_name, controller.loop),
        None,
        None,
    )


#: Controller components whose actions the engine proposes (as opposed to human/external
#: controllers like Discord/web/MCP, or the suspended no-op controller).
_CONTROLLER_AGENT_FACTORIES: dict[type, ControllerAgentFactory] = {
    LLMControllerComponent: _llm_agent_factory,
    BehaviorControllerComponent: _behavior_agent_factory,
    ScriptedControllerComponent: _scripted_agent_factory,
}
_AUTONOMOUS_COMPONENTS = tuple(_CONTROLLER_AGENT_FACTORIES)
AutonomousController = object


def register_autonomous_controller(
    component_type: type,
    agent_factory: ControllerAgentFactory,
) -> None:
    """Register an engine-driven controller component contributed by a plugin."""

    _CONTROLLER_AGENT_FACTORIES[component_type] = agent_factory
    global _AUTONOMOUS_COMPONENTS
    _AUTONOMOUS_COMPONENTS = tuple(_CONTROLLER_AGENT_FACTORIES)


def name_candidates(world: World, character: Entity) -> list[tuple[str, EntityId]]:
    """(name, id) pairs the character could be referring to: reachable entities plus the
    rooms its exits lead to. Objects/characters use their identity name; rooms use title."""
    ids = reachable_ids(world, character)
    room_id = container_of(character)
    if room_id is not None:
        ids.add(room_id)
        for _edge, target in world.get_entity(room_id).get_relationships(ExitTo):
            ids.add(target)
    # Every id collected above is a live entity: reachable_ids pre-filters, container_of follows
    # a live edge, and Relics cascades dangling ExitTo edges on world.remove(), so no has_entity
    # guard is needed before expanding contents.
    for entity_id in tuple(ids):
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
    return " ".join(value.strip() for value in call.arguments.values() if isinstance(value, str))


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
            issues.append(f"name contradiction: claimed to be {visible_names[claimed_key]}")
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
                issues.append(f"relationship contradiction: denied {name}'s {relation} status")
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
                issues.append(f"relationship contradiction: denied bond with {name}")
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
        # Async (LLM) decisions run as background tasks so a slow prompt never blocks the
        # game loop's world ticks. Keyed by character id: a character with a task still
        # running is never re-prompted, so each character has at most one decision pending.
        self._inflight: dict[str, asyncio.Task[Decision]] = {}
        # Decisions completed by background tasks since the last ``run_once``, surfaced (and
        # cleared) on the next pass so observers still see what autonomous agents chose.
        self._completed: list[Decision] = []
        # Serializes the actual provider call so there is never more than one in-flight
        # request to Ollama/OpenRouter at a time, even with many actable characters.
        self._llm_lock = asyncio.Lock()

    async def run_once(self) -> list[Decision]:
        self._tick += 1
        # A live world regeneration (admin) swaps actor.world for a brand-new World object.
        # The builder captured the old world at construction; repoint it at the current one
        # so prompts are built against the live world rather than the replaced one.
        self.builder.rebind(self.actor.world)
        decisions: list[Decision] = []
        with telemetry.span("controller.run_once", {"dispatch.tick": self._tick}) as run_span:
            # Surface decisions finished by background (LLM) tasks since the last pass.
            decisions.extend(self._drain_completed())
            actable = self._actable_characters()
            run_span.set_attribute("dispatch.actable_count", len(actable))
            for character_id in actable:
                cid = str(character_id)
                # A character whose previous decision is still being computed is never
                # re-prompted: a 60s prompt on a 30s loop yields a single pending decision,
                # not a new one every pass. The intervening passes are coalesced away rather
                # than queued — once the character is free again, the next pass rebuilds its
                # prompt from the latest world state via ``_decide_for``, so the prompt that
                # is finally delivered reflects the most recent state, never a stale one.
                if self._has_pending(cid):
                    continue
                # The actable list is snapshotted before the per-character awaits below; a
                # character can also be removed mid-loop by an in-place edit (admin patch or a
                # player interaction) at an await point. Skip ones already gone, and guard the
                # rest so a removal that races the prompt build/submit skips the character
                # instead of crashing the game loop.
                if not self.actor.world.has_entity(character_id):
                    continue
                try:
                    decision = await self._decide_for(character_id)
                except EntityNotFoundError:
                    logger.debug("skipping character %s removed mid-dispatch", character_id)
                    continue
                # ``None`` means the decision was handed to a background task and will be
                # surfaced on a later pass once it finishes.
                if decision is not None:
                    decisions.append(decision)
            run_span.set_attribute("dispatch.decision_count", len(decisions))
        return decisions

    def _has_pending(self, cid: str) -> bool:
        task = self._inflight.get(cid)
        return task is not None and not task.done()

    def _drain_completed(self) -> list[Decision]:
        if not self._completed:
            return []
        drained = self._completed
        self._completed = []
        return drained

    async def await_pending(self) -> list[Decision]:
        """Await every in-flight decision and return the decisions that completed.

        The game loop never waits like this — it lets the world keep ticking — but callers
        that need a decision applied within a bounded run (offline advancement, live tests)
        use this to block until background tasks finish.
        """
        tasks = list(self._inflight.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return self._drain_completed()

    def cancel_pending(self) -> None:
        """Cancel any in-flight decision tasks (used when the game loop stops)."""
        for task in list(self._inflight.values()):
            task.cancel()
        self._inflight.clear()

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
        factory = _CONTROLLER_AGENT_FACTORIES.get(type(component))
        if factory is None:
            raise ValueError(f"unregistered autonomous controller {type(component).__name__}")
        return factory(self, character_id, component)

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

    async def _decide_for(self, character_id: EntityId) -> Decision | None:
        """Prompt one character's agent.

        Synchronous agents (scripted/behavioral/goal-directed) resolve inline and their
        ``Decision`` is returned. An async agent's prompt is handed to a background task so a
        slow provider never blocks the world tick; ``None`` is returned and the eventual
        ``Decision`` is surfaced by a later ``run_once`` once the task finishes.
        """
        controller = self._autonomous_controller(character_id)
        assert controller is not None  # filtered in _actable_characters
        controller_id, generation, controller_component = controller
        cid = str(character_id)

        try:
            agent, model, provider = self._agent_for(cid, controller_component)
        except ValueError as exc:
            logger.warning("character %s has an unresolvable controller: %s", character_id, exc)
            return Decision(cid, None, f"wait: {exc}")

        prompted = isinstance(controller_component, LLMControllerComponent)
        with telemetry.span("agent.prompt.build", {"character.id": cid}):
            context = self.builder.build(character_id, epoch=self.actor.epoch)
            pending = self._feedback.pop(cid, None)
            if pending is not None:
                context = replace(context, warnings=(*context.warnings, pending))
            prompt = render_prompt(context)

        # Low-cardinality attributes for the decision-latency metric; spans can carry the
        # richer, higher-cardinality context (which character, what prompt, what it chose).
        metric_attrs = {
            "provider": provider or "local",
            "model": model or "unknown",
            "agent.kind": type(agent).__name__,
        }
        span_attrs = {**metric_attrs, "character.id": cid, "decision.prompted": prompted}
        if prompted and telemetry.enabled():
            span_attrs["decision.prompt"] = telemetry.attr_text(prompt)
            span_attrs["decision.prompt_chars"] = len(prompt)

        decision = agent.decide(
            prompt,
            context,
            character_id=cid,
            model=model,
            provider=provider,
            tools=tool_schemas(self.actor.action_definitions()),
        )
        if inspect.isawaitable(decision):
            # Run the provider call (and its follow-up submit) off the dispatch path so the
            # game loop is free to keep ticking the world while the model thinks.
            task = asyncio.ensure_future(
                self._await_decision(
                    character_id,
                    controller_id,
                    generation,
                    context,
                    decision,
                    span_attrs,
                    metric_attrs,
                )
            )
            self._inflight[cid] = task
            task.add_done_callback(lambda finished, key=cid: self._forget(key, finished))
            return None

        with (
            telemetry.record_duration(telemetry.record_llm_decision, metric_attrs),
            telemetry.span("agent.decide", span_attrs) as dspan,
        ):
            call = decision
            self._annotate_decision_span(dspan, call)
        return await self._finalize_decision(character_id, controller_id, generation, context, call)

    async def _await_decision(
        self,
        character_id: EntityId,
        controller_id: EntityId,
        generation: int,
        context,
        pending,
        span_attrs: dict,
        metric_attrs: dict,
    ) -> Decision:
        """Await an async agent's decision under the provider lock, then finalize it.

        The lock guarantees only one provider request runs at a time; everything after the
        request (name resolution, submission) happens outside it so the next character's
        prompt can start as soon as this one's reply lands.
        """
        cid = str(character_id)
        try:
            async with self._llm_lock:
                with (
                    telemetry.record_duration(telemetry.record_llm_decision, metric_attrs),
                    telemetry.span("agent.decide", span_attrs) as dspan,
                ):
                    call = await pending
                    self._annotate_decision_span(dspan, call)
            decision = await self._finalize_decision(
                character_id, controller_id, generation, context, call
            )
        except EntityNotFoundError:
            logger.debug("character %s removed before its decision applied", character_id)
            decision = Decision(cid, None, "skipped: removed before decision applied")
        except Exception:  # noqa: BLE001 - a background task must not crash the game loop
            logger.exception("character %s decision task failed", character_id)
            decision = Decision(cid, None, "error")
        self._completed.append(decision)
        return decision

    def _forget(self, cid: str, task: asyncio.Task[Decision]) -> None:
        if self._inflight.get(cid) is task:
            del self._inflight[cid]

    @staticmethod
    def _annotate_decision_span(dspan, call: ToolCall | None) -> None:
        if call is not None:
            dspan.set_attribute("decision.tool", call.name)
            if telemetry.enabled():
                encoded = json.dumps(call.arguments, sort_keys=True, default=str)
                dspan.set_attribute("decision.arguments", telemetry.attr_text(encoded))
        else:
            dspan.set_attribute("decision.tool", "wait")

    async def _finalize_decision(
        self,
        character_id: EntityId,
        controller_id: EntityId,
        generation: int,
        context,
        call: ToolCall | None,
    ) -> Decision:
        cid = str(character_id)
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
