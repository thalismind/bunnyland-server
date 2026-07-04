"""First-run tutorial mechanics for the public preview."""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component, Entity

from ..core.components import IdentityComponent, ReadableComponent, RoomComponent
from ..core.ecs import container_of, contents, entity_name, parse_entity_id, reachable_ids
from ..llm_agents.dispatch import ControllerDispatch, register_autonomous_controller
from ..llm_agents.tools import ToolCall
from .consumables import FoodComponent
from .needs import HungerComponent

DELIVERY_MARK = "Hungry Courier delivery complete"


@dataclass(frozen=True)
class HungryCourierControllerComponent(Component):
    """Deterministic first-run courier that still acts through normal commands."""

    food_query: str = "apple"
    letter_query: str = "courier letter"
    ledger_query: str = "delivery ledger"
    destination_title: str = "Moss Kiosk"
    route: tuple[tuple[str, str], ...] = (
        ("Clover Post Office", "east"),
        ("Market Lane", "south"),
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

    def decide(self, _prompt, _context, *, character_id: str, **_kwargs) -> ToolCall | None:
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
                    "text": "I am ready to go, but the courier letter is not where I can reach it.",
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
        named = self._reachable_match(character, self.component.food_query)
        if named is not None and named.has_component(FoodComponent):
            return named
        for entity_id in reachable_ids(self.dispatch.actor.world, character):
            entity = self.dispatch.actor.world.get_entity(entity_id)
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
    del actor
    register_autonomous_controller(
        HungryCourierControllerComponent,
        _hungry_courier_agent_factory,
    )


__all__ = [
    "DELIVERY_MARK",
    "HungryCourierAgent",
    "HungryCourierControllerComponent",
    "install_tutorial",
]
