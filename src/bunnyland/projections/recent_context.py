"""Recent-context projection (spec 11.16, 23.9).

A small rolling log of human-readable recent events per room, used by the prompt builder
for the "Recent context" section. This is volatile projection memory, not ECS truth.
"""

from __future__ import annotations

from collections import defaultdict, deque

from relics import EntityId, World

from ..core.components import IdentityComponent
from ..core.ecs import container_of, parse_entity_id
from ..core.events import (
    ActorMovedEvent,
    CharacterDiedEvent,
    CharacterDownedEvent,
    DomainEvent,
    ItemDroppedEvent,
    ItemTakenEvent,
    SpeechSaidEvent,
)

DEFAULT_CAPACITY = 20


class RecentContextProjection:
    """Keeps the last few notable events per room."""

    def __init__(self, world: World, capacity: int = DEFAULT_CAPACITY) -> None:
        self.world = world
        self._capacity = capacity
        self._log: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=capacity))

    def subscribe(self, bus) -> None:
        # Eat/drink events live in the mechanics layer; import lazily so this core
        # projection module does not form an import cycle (needs -> prompts -> projections).
        from bunnyland.foundation.needs.mechanics import DrinkConsumedEvent, FoodEatenEvent

        for event_type in (
            ActorMovedEvent,
            SpeechSaidEvent,
            ItemTakenEvent,
            ItemDroppedEvent,
            FoodEatenEvent,
            DrinkConsumedEvent,
            CharacterDownedEvent,
            CharacterDiedEvent,
        ):
            bus.subscribe(event_type, self._on_event)

    def recent(self, room_id: EntityId | str, limit: int = 5) -> tuple[str, ...]:
        entries = self._log.get(str(room_id))
        if not entries:
            return ()
        return tuple(list(entries)[-limit:])

    # -- internals ---------------------------------------------------------------------

    def _name(self, raw_id: str | None) -> str:
        entity_id = parse_entity_id(raw_id) if raw_id else None
        if entity_id is not None and self.world.has_entity(entity_id):
            entity = self.world.get_entity(entity_id)
            if entity.has_component(IdentityComponent):
                return entity.get_component(IdentityComponent).name
        return "someone"

    def _append(self, room_id: str | None, text: str) -> None:
        if room_id:
            self._log[room_id].append(text)

    def _room_of_actor(self, raw_id: str | None) -> str | None:
        entity_id = parse_entity_id(raw_id) if raw_id else None
        if entity_id is None or not self.world.has_entity(entity_id):
            return None
        room_id = container_of(self.world.get_entity(entity_id))
        return str(room_id) if room_id is not None else None

    def _on_event(self, event: DomainEvent) -> None:
        actor = self._name(event.actor_id)
        if isinstance(event, ActorMovedEvent):
            self._append(event.from_room_id, f"{actor} left.")
            self._append(event.to_room_id, f"{actor} arrived.")
        elif isinstance(event, SpeechSaidEvent):
            self._append(event.room_id, f'{actor} said: "{event.text}"')
        elif isinstance(event, ItemTakenEvent):
            self._append(event.room_id, f"{actor} picked up {self._name(event.item_id)}.")
        elif isinstance(event, ItemDroppedEvent):
            self._append(event.room_id, f"{actor} dropped {self._name(event.item_id)}.")
        elif type(event).__name__ == "FoodEatenEvent":
            self._append(event.room_id, f"{actor} ate {self._name(event.item_id)}.")
        elif type(event).__name__ == "DrinkConsumedEvent":
            self._append(event.room_id, f"{actor} drank from {self._name(event.source_id)}.")
        elif isinstance(event, CharacterDownedEvent):
            room = event.room_id or self._room_of_actor(event.actor_id)
            self._append(room, f"{actor} collapsed.")
        elif isinstance(event, CharacterDiedEvent):
            room = event.room_id or self._room_of_actor(event.actor_id)
            self._append(room, f"{actor} died.")


__all__ = ["RecentContextProjection"]
