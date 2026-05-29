"""Foundation prompt builder (spec 16).

``PromptBuilder.build`` produces a structured ``PromptContext`` from the world and
projections; ``render_prompt`` turns it into the text shown in the spec 16.2 example.
Domain-specific lines (needs, etc.) come from injected fragment providers so the builder
stays free of mechanic-specific phrasing (spec 16.3).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from relics import Entity, EntityId, World

from ..core.components import (
    ActionPointsComponent,
    AffectComponent,
    DeadComponent,
    DownedComponent,
    FocusPointsComponent,
    IdentityComponent,
    MemoryProfileComponent,
    SleepingComponent,
    SuspendedComponent,
)
from ..core.ecs import container_of
from ..core.edges import Contains, ControlledBy, Holding, Wearing
from ..projections import RecentContextProjection, RoomSummaryProjection, perceive
from ..projections.room_summary import RoomExit

# A fragment provider returns extra status lines for a character (e.g. needs).
FragmentProvider = Callable[[World, Entity], list[str]]


@dataclass(frozen=True)
class PromptContext:
    name: str
    kind: str
    status: str
    action: tuple[float, float]
    focus: tuple[float, float]
    location_title: str
    room_summary: str
    visible_characters: tuple[str, ...] = ()
    visible_objects: tuple[str, ...] = ()
    exits: tuple[str, ...] = ()
    inventory: tuple[str, ...] = ()
    held: tuple[str, ...] = ()
    worn: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    feelings: tuple[str, ...] = ()
    recent: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return "something"


def _status(character: Entity) -> str:
    if character.has_component(DeadComponent):
        return "dead"
    if character.has_component(SuspendedComponent):
        return "suspended"
    if character.has_component(DownedComponent):
        return "downed"
    if character.has_component(SleepingComponent):
        return "asleep"
    return "active"


class PromptBuilder:
    def __init__(
        self,
        world: World,
        *,
        room_summary: RoomSummaryProjection | None = None,
        recent_context: RecentContextProjection | None = None,
        memory_store=None,
        fragment_providers: Sequence[FragmentProvider] = (),
    ) -> None:
        self.world = world
        self.room_summary = room_summary or RoomSummaryProjection(world)
        self.recent_context = recent_context
        self.memory_store = memory_store
        self.fragment_providers = tuple(fragment_providers)

    def build(self, character_id: EntityId, *, epoch: int = 0) -> PromptContext:
        character = self.world.get_entity(character_id)
        identity = (
            character.get_component(IdentityComponent)
            if character.has_component(IdentityComponent)
            else None
        )
        action = self._points(character, ActionPointsComponent)
        focus = self._points(character, FocusPointsComponent)

        room_id = container_of(character)
        location_title = "nowhere"
        room_summary = ""
        exits: tuple[str, ...] = ()
        if room_id is not None:
            summary = self.room_summary.summary(room_id, epoch)
            facts = self.room_summary.facts(room_id)
            location_title = facts.title
            room_summary = summary.visible_summary
            exits = tuple(self._exit_label(e) for e in facts.exits)

        perception = perceive(self.world, character)
        visible_characters = tuple(e.name for e in perception.entities if e.is_character)
        visible_objects = tuple(e.name for e in perception.entities if not e.is_character)

        inventory, held, worn = self._equipment(character)
        feelings = (
            tuple(sorted(character.get_component(AffectComponent).labels))
            if character.has_component(AffectComponent)
            else ()
        )
        needs: list[str] = []
        for provider in self.fragment_providers:
            needs.extend(provider(self.world, character))

        recent = ()
        if self.recent_context is not None and room_id is not None:
            recent = self.recent_context.recent(room_id)

        notes = self._notes(character)
        commands = self._available_commands(
            exits=exits,
            visible_objects=visible_objects,
            visible_characters=visible_characters,
            inventory=inventory,
        )

        return PromptContext(
            name=identity.name if identity else "Unknown",
            kind=identity.kind if identity else "character",
            status=self._status_line(character),
            action=action,
            focus=focus,
            location_title=location_title,
            room_summary=room_summary,
            visible_characters=visible_characters,
            visible_objects=visible_objects,
            exits=exits,
            inventory=inventory,
            held=held,
            worn=worn,
            needs=tuple(needs),
            feelings=feelings,
            recent=tuple(recent),
            notes=notes,
            commands=commands,
        )

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def _points(character: Entity, component_type) -> tuple[float, float]:
        if character.has_component(component_type):
            c = character.get_component(component_type)
            return (round(c.current, 1), c.maximum)
        return (0.0, 0.0)

    def _status_line(self, character: Entity) -> str:
        status = _status(character)
        kind = "no controller"
        for edge, controller_id in character.get_relationships(ControlledBy):
            del edge
            controller = self.world.get_entity(controller_id)
            from ..core.controllers import (
                DiscordControllerComponent,
                LLMControllerComponent,
            )

            if controller.has_component(DiscordControllerComponent):
                kind = "controlled by a human"
            elif controller.has_component(LLMControllerComponent):
                kind = "controlled by an agent"
            else:
                kind = "suspended"
            break
        return f"{status}, {kind}"

    @staticmethod
    def _exit_label(exit_: RoomExit) -> str:
        return f"{exit_.direction} (locked)" if exit_.locked else exit_.direction

    def _equipment(
        self, character: Entity
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        inventory: list[str] = []
        for edge, child_id in character.get_relationships(Contains):
            del edge
            inventory.append(_name(self.world.get_entity(child_id)))
        held = [
            _name(self.world.get_entity(item_id))
            for _edge, item_id in character.get_relationships(Holding)
        ]
        worn = [
            _name(self.world.get_entity(item_id))
            for _edge, item_id in character.get_relationships(Wearing)
        ]
        return tuple(sorted(inventory)), tuple(sorted(held)), tuple(sorted(worn))

    def _notes(self, character: Entity) -> tuple[str, ...]:
        if self.memory_store is None or not character.has_component(MemoryProfileComponent):
            return ()
        collection = character.get_component(MemoryProfileComponent).vector_collection
        entries = self.memory_store.search(collection, mode="recent", limit=3)
        return tuple(entry.text for entry in entries)

    @staticmethod
    def _available_commands(
        *,
        exits: tuple[str, ...],
        visible_objects: tuple[str, ...],
        visible_characters: tuple[str, ...],
        inventory: tuple[str, ...],
    ) -> tuple[str, ...]:
        commands: list[str] = []
        for direction in exits:
            commands.append(f"move {direction}")
        for obj in visible_objects:
            commands.append(f"take {obj}")
            commands.append(f"use {obj}")
        if visible_characters:
            commands.append("say something to the room")
            commands.append("tell someone something privately")
        commands.append("take note")
        commands.append("remember/search notes")
        return tuple(commands)


def render_prompt(context: PromptContext) -> str:
    """Render the structured context into the spec 16.2 foundation-prompt layout."""
    lines = [f"You are {context.name}, a {context.kind}.", f"Status: {context.status}.", ""]
    lines.append("Location:")
    lines.append(context.room_summary or context.location_title)
    lines.append("")

    def section(title: str, items: tuple[str, ...]) -> None:
        if items:
            lines.append(f"{title}:")
            lines.extend(f"- {item}" for item in items)
            lines.append("")

    section("You can see", context.visible_characters + context.visible_objects)
    section("Exits", context.exits)
    section("You are carrying", context.inventory)
    section("You are holding", context.held)
    section("You are wearing", context.worn)
    section("You feel", context.feelings)
    section("Needs", context.needs)
    section("Recent context", context.recent)
    section("Notes", context.notes)

    lines.append("Points:")
    lines.append(f"Action: {context.action[0]}/{context.action[1]}")
    lines.append(f"Focus: {context.focus[0]}/{context.focus[1]}")
    lines.append("")
    section("Available commands", context.commands)
    if context.warnings:
        section("Warnings", context.warnings)
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["PromptBuilder", "PromptContext", "render_prompt"]
