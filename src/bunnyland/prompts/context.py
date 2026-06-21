"""Shared context for component-owned prompt fragments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from relics import Component, Entity, World

from ..core.ecs import container_of, contents

PerspectiveName = Literal["first-person", "second-person", "third-person"]


@dataclass(frozen=True)
class PromptPerspective:
    """Who the prompt is for, and how component text should address them."""

    viewer: Entity | None = None
    perspective: PerspectiveName = "second-person"
    language: str = "en"

    def choose(self, *, first: str, second: str, third: str) -> str:
        if self.perspective == "first-person":
            return first
        if self.perspective == "third-person":
            return third
        return second


@dataclass(frozen=True)
class PerspectivePhrase:
    """A short prompt line with first-, second-, and third-person variants."""

    first: str
    second: str
    third: str

    def render(self, perspective: PromptPerspective | PerspectiveName, **values: object) -> str:
        style = (
            perspective.perspective
            if isinstance(perspective, PromptPerspective)
            else perspective
        )
        if style == "first-person":
            text = self.first
        elif style == "third-person":
            text = self.third
        else:
            text = self.second
        if values:
            return text.format(**values)
        return text


@dataclass(frozen=True)
class ComponentPromptContext:
    """Minimal ECS context passed to component prompt formatters.

    Components can format their own state, the entity carrying that component, the prompt
    viewer, the current room, and an optional relationship target. Room sibling lookup is
    lazy so provider construction stays cheap when a component does not need it.
    """

    perspective: PromptPerspective
    entity: Entity
    room: Entity | None = None
    target: Entity | None = None
    _world: World | None = field(default=None, repr=False, compare=False)
    _sibling_cache: dict[type[Component] | None, tuple[Entity, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _inventory_cache: dict[type[Component] | None, tuple[Entity, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    def for_entity(
        cls,
        world: World,
        entity: Entity,
        *,
        perspective: PromptPerspective | None = None,
        room: Entity | None = None,
        target: Entity | None = None,
    ) -> ComponentPromptContext:
        if room is None:
            room_id = container_of(entity)
            if room_id is not None and world.has_entity(room_id):
                room = world.get_entity(room_id)
        return cls(
            perspective=perspective or PromptPerspective(viewer=entity),
            entity=entity,
            room=room,
            target=target,
            _world=world,
        )

    @property
    def viewer(self) -> Entity | None:
        return self.perspective.viewer

    @property
    def is_first_person(self) -> bool:
        """Whether this context describes the prompt viewer's own entity."""
        return self.viewer is None or self.viewer.id == self.entity.id

    @property
    def can_view_private_state(self) -> bool:
        """Whether private state in this context is scoped to the prompt viewer."""
        if self.is_first_person:
            return True
        return self.target is not None and self.viewer.id == self.target.id

    def room_siblings(self, component_type: type[Component] | None = None) -> tuple[Entity, ...]:
        if component_type in self._sibling_cache:
            return self._sibling_cache[component_type]
        if self._world is None or self.room is None:
            siblings: tuple[Entity, ...] = ()
        else:
            found: list[Entity] = []
            for sibling_id in contents(self.room):
                if sibling_id == self.entity.id or not self._world.has_entity(sibling_id):
                    continue
                sibling = self._world.get_entity(sibling_id)
                if component_type is None or sibling.has_component(component_type):
                    found.append(sibling)
            siblings = tuple(found)
        self._sibling_cache[component_type] = siblings
        return siblings

    def inventory_items(self, component_type: type[Component] | None = None) -> tuple[Entity, ...]:
        if component_type in self._inventory_cache:
            return self._inventory_cache[component_type]
        if self._world is None:
            items: tuple[Entity, ...] = ()
        else:
            found: list[Entity] = []
            for item_id in contents(self.entity):
                # Inventory edges target live entities (Relics drops edges when a target
                # is removed), so no missing-entity guard is reachable here.
                item = self._world.get_entity(item_id)
                if component_type is None or item.has_component(component_type):
                    found.append(item)
            items = tuple(found)
        self._inventory_cache[component_type] = items
        return items


__all__ = [
    "ComponentPromptContext",
    "PerspectiveName",
    "PerspectivePhrase",
    "PromptPerspective",
]
