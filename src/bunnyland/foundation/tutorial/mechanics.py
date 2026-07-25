"""First-run tutorial mechanics for the public preview."""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component, Entity

from bunnyland.foundation.consumables.components import FoodComponent
from bunnyland.foundation.needs.mechanics import HungerComponent

from ...core.components import (
    ContainerComponent,
    IdentityComponent,
    ReadableComponent,
    RoomComponent,
)
from ...core.ecs import container_of, contents, entity_name, parse_entity_id, reachable_ids
from ...core.edges import ControlledBy
from ...core.events import SpeechSaidEvent, SpeechToldEvent
from ...core.world_actor import WorldActor
from ...llm_agents.dispatch import ControllerDispatch, register_autonomous_controller
from ...llm_agents.tools import ToolCall, command_from_tool_call

DELIVERY_MARK = "Hungry Courier delivery complete"
_HELP_WORDS = frozenset({"help", "lost", "where", "which", "route", "direction", "find"})


@dataclass(frozen=True)
class TutorialGuideComponent(Component):
    """Authored same-room help that never needs an LLM provider call."""

    help_text: str


class TutorialGuideReactor:
    def __init__(self, actor: WorldActor) -> None:
        self.actor = actor

    def subscribe(self) -> None:
        self.actor.bus.subscribe(SpeechSaidEvent, self._on_speech)
        self.actor.bus.subscribe(SpeechToldEvent, self._on_speech)

    @staticmethod
    def _asks_for_help(text: str) -> bool:
        words = {word.strip(".,!?;:").lower() for word in text.split()}
        return "?" in text or bool(words.intersection(_HELP_WORDS))

    def _on_speech(self, event: SpeechSaidEvent | SpeechToldEvent) -> None:
        speaker_id = parse_entity_id(event.actor_id)
        if speaker_id is None or not self.actor.world.has_entity(speaker_id):
            return
        speaker = self.actor.world.get_entity(speaker_id)
        if speaker.has_component(TutorialGuideComponent) or not self._asks_for_help(event.text):
            return
        room_id = container_of(speaker)
        if room_id is None or not self.actor.world.has_entity(room_id):
            return
        for guide_id in sorted(contents(self.actor.world.get_entity(room_id)), key=str):
            guide = self.actor.world.get_entity(guide_id)
            if not guide.has_component(TutorialGuideComponent):
                continue
            if isinstance(event, SpeechToldEvent) and str(guide_id) not in event.target_ids:
                continue
            if any(
                command.character_id == str(guide_id) and command.command_type == "say"
                for command in self.actor.pending_submissions()
            ):
                return
            controlled = guide.get_relationships(ControlledBy)
            if not controlled:
                return
            edge, controller_id = controlled[0]
            call = ToolCall(
                "say",
                {
                    "text": guide.get_component(TutorialGuideComponent).help_text,
                    "intent": "inform",
                    "approach": "friendly",
                },
            )
            self.actor.submit_nowait(
                command_from_tool_call(
                    call,
                    character_id=str(guide_id),
                    controller_id=str(controller_id),
                    controller_generation=edge.generation,
                    submitted_at_epoch=self.actor.epoch,
                    definitions=self.actor.action_definitions(),
                )
            )
            return


@dataclass(frozen=True)
class HungryCourierControllerComponent(Component):
    """Deterministic first-run courier that still acts through normal commands."""

    food_query: str = "apple"
    letter_query: str = "courier letter"
    ledger_query: str = "delivery ledger"
    destination_title: str = "Mira's Cottage"
    route: tuple[tuple[str, str], ...] = (
        ("Apple Crossing", "south"),
        ("Old Footbridge", "west"),
        ("Mira's Cottage Lane", "in"),
    )
    act_every_ticks: int = 1


class HungryCourierAgent:
    def __init__(
        self,
        dispatch: ControllerDispatch,
        component: HungryCourierControllerComponent,
    ) -> None:
        self.dispatch = dispatch
        self.component = component

    async def decide(self, _prompt, _context, *, character_id: str, **_kwargs) -> ToolCall | None:
        character_entity_id = parse_entity_id(character_id)
        if character_entity_id is None or not self.dispatch.actor.world.has_entity(
            character_entity_id
        ):
            return None
        character = self.dispatch.actor.world.get_entity(character_entity_id)

        if self._delivered():
            return None

        if self._is_hungry(character):
            food = self._reachable_food(character)
            if food is not None:
                if food.id not in reachable_ids(self.dispatch.actor.world, character):
                    return ToolCall("take", {"item_id": entity_name(food)})
                return ToolCall("eat", {"item_id": entity_name(food)})
            return ToolCall(
                "say",
                {
                    "text": (
                        "I want to deliver the letter, but I cannot just declare myself "
                        "fed. I need real food first."
                    ),
                    "intent": "request",
                    "approach": "plain",
                },
            )

        letter = self._carried_match(character, self.component.letter_query)
        if letter is None:
            reachable_letter = self._reachable_match(character, self.component.letter_query)
            if reachable_letter is not None:
                return ToolCall("take", {"item_id": entity_name(reachable_letter)})
            return ToolCall(
                "say",
                {
                    "text": (
                        "I am ready to go, but the courier letter is not where I can reach it. "
                        "If you picked it up, drop it here in Apple Crossing so I can take it."
                    ),
                    "intent": "request",
                    "approach": "worried",
                },
            )

        room = self._room(character)
        if room is not None and self._room_title(room) == self.component.destination_title:
            ledger = self._reachable_match(character, self.component.ledger_query)
            if ledger is not None:
                return ToolCall(
                    "write",
                    {
                        "target_id": entity_name(ledger),
                        "text": f"{DELIVERY_MARK}: {entity_name(character)} delivered the letter.",
                    },
                )
            return ToolCall("drop", {"item_id": entity_name(letter)})

        direction = self._route_direction(room)
        if direction:
            return ToolCall("move", {"direction": direction})

        return ToolCall(
            "say",
            {
                "text": "I have the letter, but I need a route to the kiosk.",
                "intent": "request",
                "approach": "confused",
            },
        )

    def _room(self, character: Entity) -> Entity | None:
        room_id = container_of(character)
        if room_id is None or not self.dispatch.actor.world.has_entity(room_id):
            return None
        return self.dispatch.actor.world.get_entity(room_id)

    @staticmethod
    def _room_title(room: Entity) -> str:
        if room.has_component(RoomComponent):
            return room.get_component(RoomComponent).title
        return str(room.id)

    def _route_direction(self, room: Entity | None) -> str | None:
        if room is None:
            return None
        title = self._room_title(room)
        for route_title, direction in self.component.route:
            if title == route_title:
                return direction
        return None

    def _delivered(self) -> bool:
        for entity in self.dispatch.actor.world.query().execute_entities():
            if not entity.has_component(ReadableComponent):
                continue
            if DELIVERY_MARK in entity.get_component(ReadableComponent).text:
                return True
        return False

    @staticmethod
    def _is_hungry(character: Entity) -> bool:
        if not character.has_component(HungerComponent):
            return False
        hunger = character.get_component(HungerComponent).meter
        return hunger.value >= hunger.warning_at

    def _reachable_food(self, character: Entity) -> Entity | None:
        world = self.dispatch.actor.world
        candidate_ids = reachable_ids(world, character)
        room = self._room(character)
        if room is not None:
            for container_id in contents(room):
                if not world.has_entity(container_id):
                    continue
                container = world.get_entity(container_id)
                if not container.has_component(ContainerComponent):
                    continue
                state = container.get_component(ContainerComponent)
                if not state.open or state.locked or not state.allow_remove:
                    continue
                candidate_ids.update(
                    item_id for item_id in contents(container) if world.has_entity(item_id)
                )
        query_key = self.component.food_query.lower()
        for entity_id in sorted(candidate_ids, key=str):
            entity = world.get_entity(entity_id)
            if entity.has_component(FoodComponent) and self._matches(entity, query_key):
                return entity
        for entity_id in sorted(candidate_ids, key=str):
            entity = world.get_entity(entity_id)
            if entity.has_component(FoodComponent):
                return entity
        return None

    def _reachable_match(self, character: Entity, query: str) -> Entity | None:
        query_key = query.lower()
        for entity_id in reachable_ids(self.dispatch.actor.world, character):
            entity = self.dispatch.actor.world.get_entity(entity_id)
            if self._matches(entity, query_key):
                return entity
        return None

    def _carried_match(self, character: Entity, query: str) -> Entity | None:
        query_key = query.lower()
        for entity_id in contents(character):
            if not self.dispatch.actor.world.has_entity(entity_id):
                continue
            entity = self.dispatch.actor.world.get_entity(entity_id)
            if self._matches(entity, query_key):
                return entity
        return None

    @staticmethod
    def _matches(entity: Entity, query_key: str) -> bool:
        if not entity.has_component(IdentityComponent):
            return False
        name = entity.get_component(IdentityComponent).name.lower()
        return query_key in name


def _hungry_courier_agent_factory(
    dispatch: ControllerDispatch,
    _character_id: str,
    component: object,
):
    assert isinstance(component, HungryCourierControllerComponent)
    return HungryCourierAgent(dispatch, component), None, None


def install_tutorial(actor) -> None:
    register_autonomous_controller(
        HungryCourierControllerComponent,
        _hungry_courier_agent_factory,
    )
    TutorialGuideReactor(actor).subscribe()


__all__ = [
    "DELIVERY_MARK",
    "HungryCourierAgent",
    "HungryCourierControllerComponent",
    "TutorialGuideComponent",
    "TutorialGuideReactor",
    "install_tutorial",
]
