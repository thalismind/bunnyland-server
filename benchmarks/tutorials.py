"""Scenario-driven Ollama benchmark for the public tutorial ladder."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import logging
import os
import re
import statistics
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import JsonValue

from bunnyland.cli_defaults import OLLAMA_CLOUD_HOST
from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    FocusPointsComponent,
    IdentityComponent,
    LLMControllerComponent,
    PortableComponent,
    ReadableComponent,
    RoomComponent,
    SuspendedComponent,
    WorldActor,
    container_of,
    contents,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import (
    ActorMovedEvent,
    CommandExecutedEvent,
    DomainEvent,
    EntityInspectedEvent,
    ItemDroppedEvent,
    ItemTakenEvent,
    RoomLookedEvent,
    SpeechSaidEvent,
    SpeechToldEvent,
)
from bunnyland.foundation.needs.mechanics import FoodEatenEvent
from bunnyland.foundation.persona.mechanics import GoalComponent
from bunnyland.foundation.tutorial.mechanics import DELIVERY_MARK
from bunnyland.llm_agents import CharacterAgent, ControllerDispatch, OllamaAgent, ToolCall
from bunnyland.llm_agents.dispatch import Decision
from bunnyland.plugins import apply_plugins, bunnyland_plugins, collect_persona_fragments
from bunnyland.prompts.builder import PromptBuilder, PromptContext
from bunnyland.terminal_config import LOCAL_OLLAMA_HOST
from bunnyland.worldgen import GenOptions
from bunnyland.worldgen.examples import (
    APPLE_CROSSING_DEMO,
    BELL_GREEN_DEMO,
    CLOVER_CITY_DEMO,
)
from bunnyland.worldgen.generators import WorldGenerator
from bunnyland.worldgen.instantiate import InstantiatedWorld

SCHEMA_VERSION = 5
DEFAULT_SESSIONS = 10
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_TURN_LIMIT = 60
TURN_GAME_SECONDS = 600.0
TUTORIAL_NAMES = ("apple", "bell", "clover")

logger = logging.getLogger("bunnyland.benchmark.tutorials")

Provider = Literal["ollama-local", "ollama-cloud"]
SessionStatus = Literal["completed", "turn_limit", "timeout", "repeat_limit"]
ThinkingLevel = Literal["low", "medium", "high"]


class BenchmarkError(RuntimeError):
    """Base class for configuration, provider, and artifact failures."""


class BenchmarkConfigurationError(BenchmarkError):
    """The requested benchmark configuration cannot be run."""


class ProviderBenchmarkError(BenchmarkError):
    """Ollama could not preflight a model or answer a benchmark decision."""


@dataclass(frozen=True)
class ModelMetadata:
    model: str
    parameter_count: int | None = None
    parameter_size: str | None = None
    family: str | None = None
    quantization: str | None = None


@dataclass(frozen=True)
class BenchmarkConfig:
    models: tuple[str, ...]
    tutorials: tuple[str, ...] = TUTORIAL_NAMES
    provider: Provider = "ollama-local"
    sessions: int = DEFAULT_SESSIONS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    turn_limit: int = DEFAULT_TURN_LIMIT
    host: str | None = None
    output: Path = Path("artifacts/benchmarks/tutorials")
    api_key: str | None = field(default=None, repr=False)
    thinking: ThinkingLevel | None = None
    temperature: float | None = None
    log_thinking: bool = False
    repeat_command_guard: bool = False

    def validated(self) -> BenchmarkConfig:
        if not self.models or any(not model.strip() for model in self.models):
            raise BenchmarkConfigurationError("at least one non-empty --model is required")
        unknown = sorted(set(self.tutorials) - set(TUTORIAL_NAMES))
        if unknown:
            raise BenchmarkConfigurationError(f"unknown tutorial(s): {', '.join(unknown)}")
        if self.sessions < 1:
            raise BenchmarkConfigurationError("sessions must be positive")
        if self.timeout_seconds <= 0:
            raise BenchmarkConfigurationError("session timeout must be positive")
        if self.turn_limit < 1:
            raise BenchmarkConfigurationError("turn limit must be positive")
        if self.provider == "ollama-cloud" and not self.api_key:
            raise BenchmarkConfigurationError(
                "ollama-cloud needs OLLAMA_CLOUD_API_KEY in the environment"
            )
        return self

    @property
    def resolved_host(self) -> str:
        if self.host:
            return self.host.rstrip("/")
        if self.provider == "ollama-cloud":
            return OLLAMA_CLOUD_HOST
        return LOCAL_OLLAMA_HOST


@dataclass(frozen=True)
class Milestone:
    name: str
    evaluate: Callable[[TutorialState], bool]


@dataclass(frozen=True)
class TutorialScenario:
    name: str
    generator: WorldGenerator
    player_key: str
    tester_brief: str | None
    milestones: tuple[Milestone, ...]
    completion: Callable[[TutorialState], bool]


@dataclass
class TutorialState:
    actor: WorldActor
    generated: InstantiatedWorld
    player_id: str
    events: list[DomainEvent]
    initial_item_rooms: dict[str, str]
    turns: int = 0
    waited_game_seconds: float = 0.0


@dataclass(frozen=True)
class AgentObservation:
    prompt: str
    tool: str | None
    arguments: dict[str, object]
    latency_seconds: float
    error: str = ""


class AgentFactory(Protocol):
    def __call__(
        self, model: str, host: str, api_key: str | None
    ) -> CharacterAgent: ...


class Preflight(Protocol):
    async def __call__(
        self, models: tuple[str, ...], host: str, api_key: str | None
    ) -> tuple[ModelMetadata, ...]: ...


@dataclass(frozen=True)
class TurnTrace:
    schema_version: int
    session_id: str
    turn: int
    prompt: str
    selected_tool: str | None
    arguments: dict[str, object]
    decision_latency_seconds: float
    candidate_actions: tuple[str, ...]
    command_id: str | None
    submission_accepted: bool | None
    submission_reason: str
    receipt_status: str | None
    receipt_reason: str
    decision_summary: str
    policy_rejections: tuple[str, ...]
    provider_error: str
    consecutive_repeat_count: int
    repeat_guard_warning: bool
    result_events: tuple[dict[str, object], ...]
    milestones: tuple[str, ...]
    prompt_event_ids: tuple[str, ...] = ()
    omitted_prompt_events: int = 0


@dataclass(frozen=True)
class ModelResponseTrace:
    schema_version: int
    session_id: str
    turn: int
    response: dict[str, JsonValue]


@dataclass(frozen=True)
class SessionResult:
    schema_version: int
    session_id: str
    model: str
    tutorial: str
    run: int
    world_seed: str
    status: SessionStatus
    passed: bool
    elapsed_seconds: float
    turns: int
    milestone_results: tuple[tuple[str, bool], ...]
    valid_actions: int
    rejected_actions: int
    recovered_rejections: int
    first_confusion_signal: str | None
    repeated_blockers: tuple[tuple[str, int], ...]

    @property
    def milestone_rate(self) -> float:
        if not self.milestone_results:
            return 1.0
        return sum(passed for _name, passed in self.milestone_results) / len(
            self.milestone_results
        )


class _RecordingAgent:
    def __init__(self, agent: CharacterAgent) -> None:
        self.agent = agent
        self.observations: list[AgentObservation] = []
        self._repeat_warning = ""

    def warn_repetition(self, tool: str, arguments: Mapping[str, object]) -> None:
        self._repeat_warning = (
            "Benchmark safety warning: you have submitted the same command for five "
            f"consecutive turns: tool {tool!r} with arguments "
            f"{json.dumps(dict(arguments), sort_keys=True)}. Do not submit that exact "
            "command again; choose a different available action."
        )

    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ToolCall | None:
        effective_prompt = prompt
        if self._repeat_warning:
            effective_prompt = f"{prompt}\n\n{self._repeat_warning}"
            self._repeat_warning = ""
        started = time.perf_counter()
        try:
            call = await self.agent.decide(
                effective_prompt,
                context,
                character_id=character_id,
                model=model,
                provider=provider,
                tools=tools,
            )
        except Exception as exc:
            self.observations.append(
                AgentObservation(
                    effective_prompt, None, {}, time.perf_counter() - started, str(exc)
                )
            )
            raise
        self.observations.append(
            AgentObservation(
                prompt=effective_prompt,
                tool=call.name if call else None,
                arguments=dict(call.arguments) if call else {},
                latency_seconds=time.perf_counter() - started,
            )
        )
        return call


def _event_for_player(state: TutorialState, event_type: type[DomainEvent]) -> list[DomainEvent]:
    return [
        event
        for event in state.events
        if isinstance(event, event_type) and event.actor_id == state.player_id
    ]


def _looked(state: TutorialState, title: str) -> bool:
    return any(
        isinstance(event, RoomLookedEvent) and event.room_title == title
        for event in _event_for_player(state, RoomLookedEvent)
    )


def _inspected(state: TutorialState, *names: str) -> bool:
    expected = {name.lower() for name in names}
    return any(
        isinstance(event, EntityInspectedEvent) and event.name.lower() in expected
        for event in _event_for_player(state, EntityInspectedEvent)
    )


def _visited(state: TutorialState, title: str, *, actor_id: str | None = None) -> bool:
    room_ids = {
        str(entity.id)
        for entity in state.actor.world.query().with_all([RoomComponent]).execute_entities()
        if entity.get_component(RoomComponent).title == title
    }
    visitor = actor_id or state.player_id
    if title == _room_title_for_character(state.actor, visitor):
        return True
    return any(
        isinstance(event, ActorMovedEvent)
        and event.actor_id == visitor
        and event.to_room_id in room_ids
        for event in state.events
    )


def _room_title_for_character(actor: WorldActor, character_id: str) -> str | None:
    entity_id = next(
        (
            entity.id
            for entity in actor.world.query().with_all([CharacterComponent]).execute_entities()
            if str(entity.id) == character_id
        ),
        None,
    )
    if entity_id is None:
        return None
    room_id = container_of(actor.world.get_entity(entity_id))
    if room_id is None or not actor.world.has_entity(room_id):
        return None
    room = actor.world.get_entity(room_id)
    return room.get_component(RoomComponent).title if room.has_component(RoomComponent) else None


def _entity_id_by_name(state: TutorialState, name: str) -> str | None:
    for entity in state.actor.world.query().with_all([IdentityComponent]).execute_entities():
        if entity.get_component(IdentityComponent).name == name:
            return str(entity.id)
    return None


def _generated_object_id(state: TutorialState, key: str) -> str:
    return str(state.generated.objects[key])


def _ledger_marked(state: TutorialState) -> bool:
    return any(
        DELIVERY_MARK in entity.get_component(ReadableComponent).text
        for entity in state.actor.world.query().with_all([ReadableComponent]).execute_entities()
    )


def _apple_milestones() -> tuple[Milestone, ...]:
    def pippa_introduced(state: TutorialState) -> bool:
        pippa = _entity_id_by_name(state, "Pippa Bramble")
        return any(
            isinstance(event, SpeechSaidEvent)
            and event.actor_id == pippa
            and "Pip" in event.text
            for event in state.events
        )

    def crossing_scene(state: TutorialState) -> bool:
        return any(
            isinstance(event, RoomLookedEvent)
            and event.actor_id == state.player_id
            and event.room_title == "Apple Crossing"
            and all(label in event.summary for label in ("Pip Thistle", "courier letter"))
            for event in state.events
        )

    def took_apple(state: TutorialState) -> bool:
        apple = _generated_object_id(state, "apple")
        return any(
            isinstance(event, ItemTakenEvent)
            and event.actor_id == state.player_id
            and event.item_id == apple
            for event in state.events
        )

    def left_apple(state: TutorialState) -> bool:
        apple = _generated_object_id(state, "apple")
        return any(
            isinstance(event, ItemDroppedEvent)
            and event.actor_id == state.player_id
            and event.item_id == apple
            for event in state.events
        )

    def pip_event(state: TutorialState, event_type: type[DomainEvent], item_key: str) -> bool:
        pip = _entity_id_by_name(state, "Pip Thistle")
        item = _generated_object_id(state, item_key)
        return any(
            isinstance(event, event_type)
            and event.actor_id == pip
            and getattr(event, "item_id", None) == item
            for event in state.events
        )

    def pip_visited(state: TutorialState, title: str) -> bool:
        pip = _entity_id_by_name(state, "Pip Thistle")
        return bool(pip and _visited(state, title, actor_id=pip))

    return (
        Milestone("pippa_introduced_problem", pippa_introduced),
        Milestone("looked_in_apple_crossing", lambda state: _looked(state, "Apple Crossing")),
        Milestone("saw_courier_scene", crossing_scene),
        Milestone("visited_apple_hedge", lambda state: _visited(state, "Apple Hedge")),
        Milestone("took_red_crossing_apple", took_apple),
        Milestone(
            "returned_to_apple_crossing",
            lambda state: any(
                isinstance(event, ActorMovedEvent)
                and event.actor_id == state.player_id
                and event.direction == "west"
                and event.to_room_id == str(state.generated.rooms["crossing"])
                for event in state.events
            ),
        ),
        Milestone("left_apple_for_pip", left_apple),
        Milestone(
            "pip_ate_apple",
            lambda state: pip_event(state, FoodEatenEvent, "apple"),
        ),
        Milestone(
            "pip_took_courier_letter",
            lambda state: pip_event(state, ItemTakenEvent, "letter"),
        ),
        Milestone("pip_visited_old_footbridge", lambda state: pip_visited(state, "Old Footbridge")),
        Milestone(
            "pip_visited_miras_cottage_lane",
            lambda state: pip_visited(state, "Mira's Cottage Lane"),
        ),
        Milestone("pip_reached_miras_cottage", lambda state: pip_visited(state, "Mira's Cottage")),
        Milestone("delivery_ledger_marked", _ledger_marked),
    )


def _spoke_to_resident(state: TutorialState) -> bool:
    character_ids = {
        str(entity.id)
        for entity in state.actor.world.query().with_all([CharacterComponent]).execute_entities()
        if str(entity.id) != state.player_id
    }
    directed = any(
        isinstance(event, SpeechToldEvent)
        and event.actor_id == state.player_id
        and any(target in character_ids for target in event.target_ids)
        for event in state.events
    )
    if directed:
        return True
    occupied_rooms: set[str] = set()
    for entity in state.actor.world.query().with_all([CharacterComponent]).execute_entities():
        if str(entity.id) not in character_ids:
            continue
        room_id = container_of(entity)
        if room_id is not None:
            occupied_rooms.add(str(room_id))
    return any(
        isinstance(event, SpeechSaidEvent)
        and event.actor_id == state.player_id
        and event.room_id in occupied_rooms
        for event in state.events
    )


def _carried_item_between_rooms(state: TutorialState) -> bool:
    player = next(
        entity
        for entity in state.actor.world.query().with_all([CharacterComponent]).execute_entities()
        if str(entity.id) == state.player_id
    )
    current_room = container_of(player)
    if current_room is None:
        return False
    for item_id in contents(player):
        key = str(item_id)
        if key in state.initial_item_rooms and state.initial_item_rooms[key] != str(current_room):
            return True
    return False


def _all_milestones(state: TutorialState, milestones: tuple[Milestone, ...]) -> bool:
    return all(milestone.evaluate(state) for milestone in milestones)


def _bell_milestones() -> tuple[Milestone, ...]:
    return (
        Milestone("looked_in_bell_green", lambda state: _looked(state, "Bell Green")),
        Milestone(
            "inspected_notice_board",
            lambda state: _inspected(state, "central notice board"),
        ),
        *(Milestone(f"visited_{_slug(title)}", lambda state, title=title: _visited(state, title))
          for title in (
              "Bell Green Post Office",
              "Garden Walk",
              "Hearthwick Inn",
              "Old Bell Shrine",
          )),
        Milestone(
            "inspected_mail",
            lambda state: _inspected(state, "community mailbox", "sorted letters"),
        ),
        Milestone("spoke_to_resident", _spoke_to_resident),
        Milestone("carried_item_between_rooms", _carried_item_between_rooms),
    )


def _observed_residents_across_facilities(state: TutorialState) -> bool:
    observations: set[tuple[str, str]] = set()
    player_events = _event_for_player(state, RoomLookedEvent)
    residents = {
        entity.get_component(IdentityComponent).name
        for entity in state.actor.world.query().with_all([CharacterComponent]).execute_entities()
        if str(entity.id) != state.player_id and entity.has_component(IdentityComponent)
    }
    for event in player_events:
        assert isinstance(event, RoomLookedEvent)
        for resident in residents:
            if resident in event.summary:
                observations.add((event.room_title, resident))
    return len({room for room, _resident in observations}) >= 3 and len(
        {resident for _room, resident in observations}
    ) >= 3


def _waited_for_activity(state: TutorialState) -> bool:
    waits = sum(
        isinstance(event, CommandExecutedEvent)
        and event.actor_id == state.player_id
        and event.command_type == "wait"
        for event in state.events
    )
    return waits >= 3 and state.waited_game_seconds >= 3 * TURN_GAME_SECONDS


def _clover_milestones() -> tuple[Milestone, ...]:
    return (
        Milestone("looked_in_clover_city_lobby", lambda state: _looked(state, "Clover City Lobby")),
        Milestone("inspected_daily_bulletin", lambda state: _inspected(state, "daily bulletin")),
        *(Milestone(f"visited_{_slug(title)}", lambda state, title=title: _visited(state, title))
          for title in (
              "Mailroom",
              "Elevator",
              "Laundry Room",
              "Community Kitchen",
              "Rooftop Garden",
              "Security Office",
              "Street Stop",
          )),
        Milestone(
            "inspected_city_record",
            lambda state: _inspected(state, "parcel locker", "incident log"),
        ),
        Milestone("observed_three_residents", _observed_residents_across_facilities),
        Milestone("waited_for_world_activity", _waited_for_activity),
    )


def tutorial_scenarios() -> dict[str, TutorialScenario]:
    apple = _apple_milestones()
    bell = _bell_milestones()
    clover = _clover_milestones()
    return {
        "apple": TutorialScenario(
            name="apple",
            generator=APPLE_CROSSING_DEMO,
            player_key="player",
            tester_brief=None,
            milestones=apple,
            completion=_ledger_marked,
        ),
        "bell": TutorialScenario(
            name="bell",
            generator=BELL_GREEN_DEMO,
            player_key="bram",
            tester_brief=(
                "Orient yourself in Bell Green: read the notice board, visit the documented "
                "destinations, interact with a resident, and carry an item between rooms."
            ),
            milestones=bell,
            completion=lambda state: _all_milestones(state, bell),
        ),
        "clover": TutorialScenario(
            name="clover",
            generator=CLOVER_CITY_DEMO,
            player_key="ada",
            tester_brief=(
                "Orient yourself in Clover City: read the daily bulletin, inspect the city's "
                "major facilities, and observe city activity."
            ),
            milestones=clover,
            completion=lambda state: _all_milestones(state, clover),
        ),
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _parameter_count(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMBT])?", value.upper())
    if match is None:
        return None
    multipliers = {None: 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}
    return int(float(match.group(1)) * multipliers[match.group(2)])


async def preflight_ollama_models(
    models: tuple[str, ...], host: str, api_key: str | None
) -> tuple[ModelMetadata, ...]:
    """Confirm models exist with Ollama's show endpoint; never pull or record credentials."""

    try:
        import ollama
    except ImportError as exc:
        raise ProviderBenchmarkError(
            "tutorial benchmark requires the 'llm' extra: uv sync --extra llm"
        ) from exc
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    client = ollama.AsyncClient(host=host, headers=headers)
    metadata = []
    for model in models:
        try:
            response = await client.show(model)
        except Exception as exc:
            raise ProviderBenchmarkError(
                f"Ollama model preflight failed for {model!r}: {exc}"
            ) from exc
        details = response.details
        parameter_size = details.parameter_size if details else None
        metadata.append(
            ModelMetadata(
                model=model,
                parameter_count=_parameter_count(parameter_size),
                parameter_size=parameter_size,
                family=details.family if details else None,
                quantization=details.quantization_level if details else None,
            )
        )
    return tuple(metadata)


def _default_agent_factory(model: str, host: str, api_key: str | None) -> CharacterAgent:
    return OllamaAgent(model=model, host=host, api_key=api_key, history_turns=60)


def _record_event(events: list[DomainEvent]) -> Callable[[DomainEvent], None]:
    def record(event: DomainEvent) -> None:
        events.append(event)

    return record


def _set_goal(character, brief: str) -> None:
    if character.has_component(GoalComponent):
        replace_component(character, GoalComponent(active_goals=(brief,)))
    else:
        character.add_component(GoalComponent(active_goals=(brief,)))


async def _build_session(
    scenario: TutorialScenario,
    *,
    model: str,
    provider: Provider,
    seed: str,
    agent: CharacterAgent,
) -> tuple[TutorialState, ControllerDispatch, _RecordingAgent]:
    actor = WorldActor()
    plugins = bunnyland_plugins()
    apply_plugins(plugins, actor)
    events: list[DomainEvent] = []
    actor.bus.subscribe(
        DomainEvent,
        _record_event(events),
        reaction_id="tutorial-benchmark-events",
        external=True,
    )
    generated = await scenario.generator.generate(actor, seed, GenOptions())
    events.clear()
    player_id = generated.characters[scenario.player_key]
    player = actor.world.get_entity(player_id)
    if player.has_component(SuspendedComponent):
        player.remove_component(SuspendedComponent)
    replace_component(
        player,
        replace(player.get_component(ActionPointsComponent), current=100.0, maximum=100.0),
    )
    replace_component(
        player,
        replace(player.get_component(FocusPointsComponent), current=100.0, maximum=100.0),
    )
    if scenario.tester_brief:
        _set_goal(player, scenario.tester_brief)
    controller = spawn_entity(
        actor.world,
        [LLMControllerComponent(profile_name="tutorial-benchmark", model=model, provider=provider)],
    )
    actor.assign_controller(player.id, controller.id)
    initial_item_rooms = {
        str(entity.id): str(room_id)
        for entity in actor.world.query().with_all([PortableComponent]).execute_entities()
        if (room_id := container_of(entity)) is not None
    }
    recording = _RecordingAgent(agent)
    dispatch = ControllerDispatch(
        actor,
        PromptBuilder(
            actor.world,
            fragment_providers=actor.prompt_fragment_providers,
            persona_providers=collect_persona_fragments(plugins),
        ),
        recording,
    )
    return (
        TutorialState(actor, generated, str(player_id), events, initial_item_rooms),
        dispatch,
        recording,
    )


def _serialize_event(event: DomainEvent) -> dict[str, object]:
    return dict(event.model_dump(mode="json"))


def _blocker_signature(decision: Decision, *, progressed: bool) -> str | None:
    raw = ""
    if decision.receipt_status in {"rejected", "policy_rejected"}:
        raw = decision.receipt_reason or decision.summary
    elif decision.receipt_status == "wait" and not progressed:
        raw = "wait_without_milestone_progress"
    if not raw:
        return None
    normalized = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", raw.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _recovery_count(decisions: Sequence[Decision]) -> int:
    rejected = [
        index
        for index, decision in enumerate(decisions)
        if decision.receipt_status in {"rejected", "policy_rejected"}
    ]
    return sum(
        any(
            candidate.receipt_status == "committed"
            for candidate in decisions[index + 1 : index + 3]
        )
        for index in rejected
    )


async def run_session(
    scenario: TutorialScenario,
    *,
    model: str,
    provider: Provider,
    run: int,
    timeout_seconds: float,
    turn_limit: int,
    agent: CharacterAgent,
    on_trace_recorded: Callable[[TurnTrace], None] | None = None,
    repeat_command_guard: bool = False,
) -> tuple[SessionResult, tuple[TurnTrace, ...]]:
    session_id = f"{scenario.name}-{_slug(model)}-{run:02d}"
    seed = f"tutorial-benchmark-{session_id}"
    state, dispatch, recording = await _build_session(
        scenario, model=model, provider=provider, seed=seed, agent=agent
    )
    decisions: list[Decision] = []
    traces: list[TurnTrace] = []
    blocker_counts: Counter[str] = Counter()
    first_confusion: str | None = None
    completed = scenario.completion(state)
    repeated_command: tuple[str, str] | None = None
    consecutive_repeat_count = 0
    repeat_guard_ended = False
    started = time.perf_counter()

    async def play() -> None:
        nonlocal completed, consecutive_repeat_count, first_confusion
        nonlocal repeated_command, repeat_guard_ended
        for turn in range(1, turn_limit + 1):
            before = {
                milestone.name for milestone in scenario.milestones if milestone.evaluate(state)
            }
            observation_index = len(recording.observations)
            immediate = await dispatch.run_once()
            pending = await dispatch.await_pending()
            turn_decisions = [
                decision
                for decision in (*immediate, *pending)
                if decision.character_id == state.player_id
            ]
            await state.actor.tick(TURN_GAME_SECONDS)
            turn_decisions = [
                decision.with_receipt(
                    state.actor.receipt_for(decision.command_id)
                    if decision.command_id
                    else None
                )
                for decision in turn_decisions
            ]
            state.turns = turn
            if any(
                decision.selected_action == "wait" and decision.receipt_status == "committed"
                for decision in turn_decisions
            ):
                state.waited_game_seconds += TURN_GAME_SECONDS
            receipt_events = {event.event_id: event for event in state.events}
            after = {
                milestone.name for milestone in scenario.milestones if milestone.evaluate(state)
            }
            progressed = len(after) > len(before)
            decisions.extend(turn_decisions)
            observation = (
                recording.observations[observation_index]
                if len(recording.observations) > observation_index
                else AgentObservation("", None, {}, 0.0)
            )
            decision = (
                turn_decisions[-1]
                if turn_decisions
                else Decision(state.player_id, None, "wait")
            )
            command_key = (
                observation.tool or "wait",
                json.dumps(observation.arguments, sort_keys=True),
            )
            if command_key == repeated_command:
                consecutive_repeat_count += 1
            else:
                repeated_command = command_key
                consecutive_repeat_count = 1
            repeat_warning = repeat_command_guard and consecutive_repeat_count == 5
            if repeat_warning:
                recording.warn_repetition(command_key[0], observation.arguments)
            signature = _blocker_signature(decision, progressed=progressed)
            if signature:
                blocker_counts[signature] += 1
                if first_confusion is None:
                    first_confusion = signature
            provider_error = observation.error or (
                "provider error"
                if any(item.summary == "error" for item in turn_decisions)
                else ""
            )
            trace = TurnTrace(
                schema_version=SCHEMA_VERSION,
                session_id=session_id,
                turn=turn,
                prompt=observation.prompt,
                selected_tool=observation.tool,
                arguments=observation.arguments,
                decision_latency_seconds=observation.latency_seconds,
                candidate_actions=decision.candidate_actions,
                command_id=decision.command_id,
                submission_accepted=decision.submission_accepted,
                submission_reason=decision.submission_reason,
                receipt_status=decision.receipt_status,
                receipt_reason=decision.receipt_reason,
                decision_summary=decision.summary,
                policy_rejections=decision.policy_rejections,
                provider_error=provider_error,
                consecutive_repeat_count=consecutive_repeat_count,
                repeat_guard_warning=repeat_warning,
                result_events=tuple(
                    _serialize_event(receipt_events[event_id])
                    for event_id in decision.result_event_ids
                    if event_id in receipt_events
                ),
                milestones=tuple(sorted(after)),
                prompt_event_ids=decision.prompt_event_ids,
                omitted_prompt_events=decision.omitted_prompt_events,
            )
            traces.append(trace)
            if on_trace_recorded is not None:
                on_trace_recorded(trace)
            if provider_error:
                raise ProviderBenchmarkError(
                    f"Ollama decision failed in {session_id}: {provider_error}"
                )
            completed = scenario.completion(state)
            if completed:
                return
            if repeat_command_guard and consecutive_repeat_count >= 10:
                repeat_guard_ended = True
                return

    status: SessionStatus
    try:
        async with asyncio.timeout(timeout_seconds):
            await play()
    except TimeoutError:
        dispatch.cancel_pending()
        status = "timeout"
    else:
        status = (
            "completed"
            if completed
            else "repeat_limit"
            if repeat_guard_ended
            else "turn_limit"
        )
    elapsed = time.perf_counter() - started
    milestone_results = tuple(
        (milestone.name, bool(milestone.evaluate(state))) for milestone in scenario.milestones
    )
    valid = sum(decision.receipt_status == "committed" for decision in decisions)
    rejected = sum(
        decision.receipt_status in {"rejected", "policy_rejected"} for decision in decisions
    )
    result = SessionResult(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        model=model,
        tutorial=scenario.name,
        run=run,
        world_seed=seed,
        status=status,
        passed=completed and elapsed <= timeout_seconds,
        elapsed_seconds=elapsed,
        turns=state.turns,
        milestone_results=milestone_results,
        valid_actions=valid,
        rejected_actions=rejected,
        recovered_rejections=_recovery_count(decisions),
        first_confusion_signal=first_confusion,
        repeated_blockers=tuple(
            sorted((key, count) for key, count in blocker_counts.items() if count > 1)
        ),
    )
    return result, tuple(traces)


def _median(values: Sequence[float | int]) -> float | None:
    return float(statistics.median(values)) if values else None


def _ranking_row(model: str, sessions: Sequence[SessionResult]) -> dict[str, object]:
    completed = [session for session in sessions if session.passed]
    attempted = sum(session.valid_actions + session.rejected_actions for session in sessions)
    rejected = sum(session.rejected_actions for session in sessions)
    return {
        "model": model,
        "sessions": len(sessions),
        "completed_within_session_limit": len(completed),
        "pass_rate": len(completed) / len(sessions) if sessions else 0.0,
        "median_completion_seconds": _median([session.elapsed_seconds for session in completed]),
        "median_completion_turns": _median([session.turns for session in completed]),
        "milestone_completion_rate": (
            sum(session.milestone_rate for session in sessions) / len(sessions) if sessions else 0.0
        ),
        "valid_actions": sum(session.valid_actions for session in sessions),
        "rejections": rejected,
        "recovered_rejections": sum(session.recovered_rejections for session in sessions),
        "valid_action_rate": (attempted - rejected) / attempted if attempted else 1.0,
        "rejection_recovery_rate": (
            sum(session.recovered_rejections for session in sessions) / rejected
            if rejected
            else 1.0
        ),
    }


def _rank(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    def key(row: dict[str, object]) -> tuple[float, float, float, float, float, str]:
        median_seconds = row["median_completion_seconds"]
        median_turns = row["median_completion_turns"]
        return (
            -float(row["completed_within_session_limit"]),
            -float(row["pass_rate"]),
            float(median_seconds) if median_seconds is not None else float("inf"),
            float(median_turns) if median_turns is not None else float("inf"),
            -float(row["milestone_completion_rate"]),
            str(row["model"]),
        )

    ranked = sorted(rows, key=key)
    return [dict(row, rank=index) for index, row in enumerate(ranked, 1)]


def summarize(
    results: Sequence[SessionResult], metadata: Sequence[ModelMetadata], tutorials: Sequence[str]
) -> dict[str, object]:
    models = tuple(item.model for item in metadata)
    tutorial_rankings = {
        tutorial: _rank(
            [
                _ranking_row(
                    model,
                    [
                        result
                        for result in results
                        if result.model == model and result.tutorial == tutorial
                    ],
                )
                for model in models
            ]
        )
        for tutorial in tutorials
    }
    complete_ladder = set(TUTORIAL_NAMES).issubset(tutorials)
    ladder_rankings = (
        _rank(
            [
                _ranking_row(model, [result for result in results if result.model == model])
                for model in models
            ]
        )
        if complete_ladder
        else []
    )
    parameter_counts = {item.model: item.parameter_count for item in metadata}

    def smallest(qualifying: Sequence[str]) -> str | None:
        known = [model for model in qualifying if parameter_counts.get(model) is not None]
        return min(known, key=lambda model: int(parameter_counts[model] or 0)) if known else None

    thresholds: dict[str, str | None] = {}
    for tutorial in tutorials:
        passing = [
            model
            for model in models
            if sum(
                result.passed
                for result in results
                if result.model == model and result.tutorial == tutorial
            )
            >= 8
        ]
        thresholds[tutorial] = smallest(passing)
    full = (
        [
            model
            for model in models
            if all(
                sum(
                    result.passed
                    for result in results
                    if result.model == model and result.tutorial == tutorial
                )
                >= 8
                for tutorial in TUTORIAL_NAMES
            )
        ]
        if complete_ladder
        else []
    )
    thresholds["full_ladder"] = smallest(full)
    return {
        "schema_version": SCHEMA_VERSION,
        "tutorial_rankings": tutorial_rankings,
        "full_ladder_ranking": ladder_rankings,
        "smallest_model_reaching_8_of_10": thresholds,
    }


async def run_benchmark(
    config: BenchmarkConfig,
    *,
    agent_factory: AgentFactory | None = None,
    preflight: Preflight = preflight_ollama_models,
    on_session_completed: Callable[[SessionResult], None] | None = None,
    on_trace_recorded: Callable[[TurnTrace], None] | None = None,
    on_response_recorded: Callable[[ModelResponseTrace], None] | None = None,
    on_preflight_completed: Callable[[tuple[ModelMetadata, ...]], None] | None = None,
) -> tuple[
    dict[str, object],
    tuple[SessionResult, ...],
    tuple[TurnTrace, ...],
    tuple[ModelResponseTrace, ...],
    tuple[ModelMetadata, ...],
]:
    config = config.validated()
    metadata = await preflight(config.models, config.resolved_host, config.api_key)
    if on_preflight_completed is not None:
        on_preflight_completed(metadata)
    scenarios = tutorial_scenarios()
    results: list[SessionResult] = []
    traces: list[TurnTrace] = []
    responses: list[ModelResponseTrace] = []

    def response_recorder(
        current_session_id: str,
    ) -> Callable[[dict[str, JsonValue]], None]:
        response_turn = 0

        def record(response: dict[str, JsonValue]) -> None:
            nonlocal response_turn
            response_turn += 1
            trace = ModelResponseTrace(
                schema_version=SCHEMA_VERSION,
                session_id=current_session_id,
                turn=response_turn,
                response=response,
            )
            responses.append(trace)
            if on_response_recorded is not None:
                on_response_recorded(trace)

        return record

    for model in config.models:
        for tutorial in config.tutorials:
            for run in range(1, config.sessions + 1):
                session_id = f"{tutorial}-{_slug(model)}-{run:02d}"
                record_response = response_recorder(session_id)
                agent = (
                    agent_factory(model, config.resolved_host, config.api_key)
                    if agent_factory is not None
                    else OllamaAgent(
                        model=model,
                        host=config.resolved_host,
                        api_key=config.api_key,
                        history_turns=60,
                        think=config.thinking,
                        temperature=config.temperature,
                        response_observer=record_response,
                        log_thinking=config.log_thinking,
                    )
                )
                result, session_traces = await run_session(
                    scenarios[tutorial],
                    model=model,
                    provider=config.provider,
                    run=run,
                    timeout_seconds=config.timeout_seconds,
                    turn_limit=config.turn_limit,
                    agent=agent,
                    on_trace_recorded=on_trace_recorded,
                    repeat_command_guard=config.repeat_command_guard,
                )
                results.append(result)
                traces.extend(session_traces)
                if on_session_completed is not None:
                    on_session_completed(result)
    return (
        summarize(results, metadata, config.tutorials),
        tuple(results),
        tuple(traces),
        tuple(responses),
        metadata,
    )


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _safe_endpoint(value: str) -> str:
    """Remove URL credentials, query values, and fragments from recorded endpoints."""

    parsed = urlsplit(value)
    if not parsed.hostname:
        return value.split("?", 1)[0].split("#", 1)[0]
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{hostname}:{parsed.port}" if parsed.port is not None else hostname
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def write_artifacts(
    config: BenchmarkConfig,
    summary: Mapping[str, object],
    results: Sequence[SessionResult],
    traces: Sequence[TurnTrace],
    responses: Sequence[ModelResponseTrace],
    metadata: Sequence[ModelMetadata],
) -> None:
    config.output.mkdir(parents=True, exist_ok=True)
    _write_json(config.output / "manifest.json", _manifest(config, metadata))
    _write_json(config.output / "summary.json", dict(summary))
    _write_jsonl(config.output / "sessions.jsonl", [asdict(result) for result in results])
    _write_jsonl(config.output / "traces.jsonl", [asdict(trace) for trace in traces])
    _write_jsonl(config.output / "responses.jsonl", [asdict(response) for response in responses])
    (config.output / "report.md").write_text(
        render_report(config, summary, metadata), encoding="utf-8"
    )
    log_path = config.output / "benchmark.log"
    if not log_path.exists():
        log_path.write_text("benchmark artifacts written\n", encoding="utf-8")


def _manifest(
    config: BenchmarkConfig, metadata: Sequence[ModelMetadata]
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "ollama-tutorial-ladder",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": _commit(),
        "bunnyland_version": importlib.metadata.version("bunnyland"),
        "provider": config.provider,
        "host": _safe_endpoint(config.resolved_host),
        "models": [asdict(item) for item in metadata],
        "tutorials": list(config.tutorials),
        "sessions_per_model_tutorial": config.sessions,
        "session_timeout_seconds": config.timeout_seconds,
        "turn_limit": config.turn_limit,
        "turn_game_seconds": TURN_GAME_SECONDS,
        "thinking": config.thinking,
        "temperature": config.temperature,
        "log_thinking": config.log_thinking,
        "repeat_command_guard": config.repeat_command_guard,
    }


def render_report(
    config: BenchmarkConfig,
    summary: Mapping[str, object],
    metadata: Sequence[ModelMetadata],
) -> str:
    temperature = (
        config.temperature if config.temperature is not None else "provider default"
    )
    lines = [
        "# Ollama tutorial-ladder comparison",
        "",
        f"Provider: `{config.provider}`  ",
        f"Sessions per model/tutorial: `{config.sessions}`  ",
        f"Session timeout: `{config.timeout_seconds:g}` seconds  ",
        f"Turn limit: `{config.turn_limit}`  ",
        f"Thinking: `{config.thinking or 'provider default'}`  ",
        f"Temperature: `{temperature}`  ",
        f"Thinking logged: `{'yes' if config.log_thinking else 'no'}`",
        f"Repeat-command guard: `{'enabled' if config.repeat_command_guard else 'disabled'}`",
        "",
        "## Models",
        "",
        "| Model | Parameters | Family | Quantization |",
        "| --- | ---: | --- | --- |",
    ]
    for item in metadata:
        parameters = item.parameter_size or (
            str(item.parameter_count) if item.parameter_count is not None else "unknown"
        )
        lines.append(
            f"| `{item.model}` | {parameters} | {item.family or 'unknown'} | "
            f"{item.quantization or 'unknown'} |"
        )

    tutorial_rankings = summary.get("tutorial_rankings")
    if isinstance(tutorial_rankings, dict):
        for tutorial in config.tutorials:
            lines.extend(
                (
                    "",
                    f"## {tutorial.title()}",
                    "",
                    "| Rank | Model | Passes | Pass rate | Median seconds | Median turns | "
                    "Milestones | Valid | Rejected | Recovered |",
                    "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                )
            )
            rows = tutorial_rankings.get(tutorial)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"| {row.get('rank', '')} | `{row.get('model', '')}` | "
                    f"{row.get('completed_within_session_limit', 0)}/{row.get('sessions', 0)} | "
                    f"{_percent(row.get('pass_rate'))} | "
                    f"{_number(row.get('median_completion_seconds'))} | "
                    f"{_number(row.get('median_completion_turns'))} | "
                    f"{_percent(row.get('milestone_completion_rate'))} | "
                    f"{row.get('valid_actions', 0)} | {row.get('rejections', 0)} | "
                    f"{row.get('recovered_rejections', 0)} |"
                )

    ladder_ranking = summary.get("full_ladder_ranking")
    if isinstance(ladder_ranking, list) and ladder_ranking:
        lines.extend(
            (
                "",
                "## Full ladder",
                "",
                "| Rank | Model | Passes | Pass rate | Median seconds | Median turns | "
                "Milestones | Valid | Rejected | Recovered |",
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            )
        )
        for row in ladder_ranking:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"| {row.get('rank', '')} | `{row.get('model', '')}` | "
                f"{row.get('completed_within_session_limit', 0)}/{row.get('sessions', 0)} | "
                f"{_percent(row.get('pass_rate'))} | "
                f"{_number(row.get('median_completion_seconds'))} | "
                f"{_number(row.get('median_completion_turns'))} | "
                f"{_percent(row.get('milestone_completion_rate'))} | "
                f"{row.get('valid_actions', 0)} | {row.get('rejections', 0)} | "
                f"{row.get('recovered_rejections', 0)} |"
            )

    thresholds = summary.get("smallest_model_reaching_8_of_10")
    if isinstance(thresholds, dict):
        lines.extend(("", "## Smallest model reaching 8/10", ""))
        for tutorial in (*config.tutorials, "full_ladder"):
            if tutorial == "full_ladder" and not ladder_ranking:
                continue
            value = thresholds.get(tutorial)
            label = "Full ladder" if tutorial == "full_ladder" else tutorial.title()
            result = f"`{value}`" if isinstance(value, str) else "Not established"
            lines.append(f"- {label}: {result}")

    lines.extend(
        (
            "",
            "## Adding models",
            "",
            "Run the benchmark again in a new output directory with these model flags plus "
            "additional repeatable `--model` options. Keeping the prior models in the run "
            "preserves directly comparable provider timing and rankings.",
            "",
        )
    )
    return "\n".join(lines)


def _number(value: object) -> str:
    return f"{float(value):.2f}" if isinstance(value, int | float) else "—"


def _percent(value: object) -> str:
    return f"{100 * float(value):.1f}%" if isinstance(value, int | float) else "—"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: Sequence[object]) -> None:
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def _append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class LiveArtifactWriter:
    """Durably checkpoint a running benchmark at every turn and session boundary."""

    def __init__(self, config: BenchmarkConfig) -> None:
        self.config = config
        self.metadata: tuple[ModelMetadata, ...] = ()
        self.results: list[SessionResult] = []

    def start(self) -> None:
        self.config.output.mkdir(parents=True, exist_ok=True)
        _write_jsonl(self.config.output / "sessions.jsonl", ())
        _write_jsonl(self.config.output / "traces.jsonl", ())
        _write_jsonl(self.config.output / "responses.jsonl", ())
        logger.info(
            "benchmark started provider=%s models=%s tutorials=%s sessions=%d "
            "timeout=%g turn_limit=%d thinking=%s temperature=%s log_thinking=%s "
            "repeat_command_guard=%s",
            self.config.provider,
            ",".join(self.config.models),
            ",".join(self.config.tutorials),
            self.config.sessions,
            self.config.timeout_seconds,
            self.config.turn_limit,
            self.config.thinking or "provider-default",
            self.config.temperature if self.config.temperature is not None else "provider-default",
            self.config.log_thinking,
            self.config.repeat_command_guard,
        )

    def record_preflight(self, metadata: tuple[ModelMetadata, ...]) -> None:
        self.metadata = metadata
        _write_json(self.config.output / "manifest.json", _manifest(self.config, metadata))
        logger.info("preflight completed models=%s", ",".join(item.model for item in metadata))

    def record_trace(self, trace: TurnTrace) -> None:
        _append_jsonl(self.config.output / "traces.jsonl", asdict(trace))
        logger.info(
            "turn session=%s turn=%d tool=%s receipt=%s latency=%.3f milestones=%s",
            trace.session_id,
            trace.turn,
            trace.selected_tool or "wait",
            trace.receipt_status or "none",
            trace.decision_latency_seconds,
            ",".join(trace.milestones),
        )

    def record_response(self, response: ModelResponseTrace) -> None:
        _append_jsonl(self.config.output / "responses.jsonl", asdict(response))
        message = response.response.get("message")
        thinking_logged = isinstance(message, dict) and bool(message.get("thinking"))
        logger.info(
            "response session=%s turn=%d thinking_logged=%s",
            response.session_id,
            response.turn,
            thinking_logged,
        )

    def record_session(self, result: SessionResult) -> None:
        self.results.append(result)
        _append_jsonl(self.config.output / "sessions.jsonl", asdict(result))
        if self.metadata:
            summary = summarize(self.results, self.metadata, self.config.tutorials)
            _write_json(self.config.output / "summary.json", summary)
            (self.config.output / "report.md").write_text(
                render_report(self.config, summary, self.metadata), encoding="utf-8"
            )
        logger.info(
            "session completed id=%s status=%s passed=%s turns=%d elapsed=%.3f",
            result.session_id,
            result.status,
            result.passed,
            result.turns,
            result.elapsed_seconds,
        )


def _benchmark_log_handler(output: Path) -> logging.Handler:
    output.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(output / "benchmark.log", mode="w", encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    return handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True, help="Ollama model (repeatable)")
    parser.add_argument(
        "--tutorial",
        action="append",
        choices=TUTORIAL_NAMES,
        help="tutorial to run (repeatable; default: all)",
    )
    parser.add_argument(
        "--provider",
        choices=("ollama-local", "ollama-cloud"),
        default="ollama-local",
    )
    parser.add_argument("--host", help="Ollama endpoint override")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--session-timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--turn-limit", type=int, default=DEFAULT_TURN_LIMIT)
    parser.add_argument("--thinking", choices=("low", "medium", "high"))
    parser.add_argument("--temperature", type=float)
    parser.add_argument(
        "--log-thinking",
        action="store_true",
        help="include Ollama's thinking field in responses.jsonl (default: omit)",
    )
    parser.add_argument(
        "--repeat-command-guard",
        action="store_true",
        help="warn after 5 identical consecutive calls and end the session after 10",
    )
    parser.add_argument("--output", type=Path, default=BenchmarkConfig.output)
    return parser


async def _async_main(args: argparse.Namespace) -> None:
    config = BenchmarkConfig(
        models=tuple(dict.fromkeys(args.model)),
        tutorials=tuple(dict.fromkeys(args.tutorial or TUTORIAL_NAMES)),
        provider=args.provider,
        sessions=args.sessions,
        timeout_seconds=args.session_timeout,
        turn_limit=args.turn_limit,
        host=args.host or os.environ.get("OLLAMA_HOST"),
        output=args.output,
        api_key=os.environ.get("OLLAMA_CLOUD_API_KEY") if args.provider == "ollama-cloud" else None,
        thinking=args.thinking,
        temperature=args.temperature,
        log_thinking=args.log_thinking,
        repeat_command_guard=args.repeat_command_guard,
    )
    completed_count = 0
    total_sessions = len(config.models) * len(config.tutorials) * config.sessions
    artifact_writer = LiveArtifactWriter(config)
    log_handler = _benchmark_log_handler(config.output)
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    verbose_loggers = (
        logger,
        logging.getLogger("bunnyland.llm"),
        logging.getLogger("bunnyland.llm_agents.dispatch"),
    )
    previous_levels = tuple(item.level for item in verbose_loggers)
    for item in verbose_loggers:
        item.setLevel(logging.INFO)
    artifact_writer.start()

    def progress(result: SessionResult) -> None:
        nonlocal completed_count
        completed_count += 1
        artifact_writer.record_session(result)
        print(
            f"[{completed_count}/{total_sessions}] {result.session_id}: {result.status}, "
            f"passed={result.passed}, turns={result.turns}, "
            f"elapsed={result.elapsed_seconds:.1f}s",
            flush=True,
        )

    try:
        summary, results, traces, responses, metadata = await run_benchmark(
            config,
            on_session_completed=progress,
            on_trace_recorded=artifact_writer.record_trace,
            on_response_recorded=artifact_writer.record_response,
            on_preflight_completed=artifact_writer.record_preflight,
        )
        write_artifacts(config, summary, results, traces, responses, metadata)
        logger.info(
            "benchmark completed sessions=%d traces=%d responses=%d",
            len(results),
            len(traces),
            len(responses),
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
    except Exception:
        logger.exception("benchmark failed; checkpoint artifacts retained")
        raise
    finally:
        for item, level in zip(verbose_loggers, previous_levels, strict=True):
            item.setLevel(level)
        root_logger.removeHandler(log_handler)
        log_handler.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(_async_main(args))
    except (BenchmarkError, OSError, TypeError, ValueError) as exc:
        print(f"benchmark-tutorials: {exc}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
