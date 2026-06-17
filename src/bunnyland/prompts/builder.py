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
from ..core.ecs import container_of, parse_entity_id
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
    persona: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()  # domain fragments: needs, weather, relationships, ...
    feelings: tuple[str, ...] = ()
    social_cues: tuple[str, ...] = ()
    recent: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    recall: tuple[str, ...] = ()
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
        persona_providers: Sequence[FragmentProvider] = (),
        recall_limit: int = 3,
        recall_budget_chars: int = 900,
        recall_line_chars: int = 240,
        include_entity_ids: bool = False,
    ) -> None:
        self.world = world
        # Annotate perceived entities, exits, and carried items with their entity ids.
        # Off by default (keeps narrative prompts clean); useful for MCP play/debugging.
        self.include_entity_ids = include_entity_ids
        # Attach the projection's ECS observers so its cache invalidates as the room
        # changes (idempotent; mutations dirty the room on the next tick).
        self.room_summary = (room_summary or RoomSummaryProjection(world)).attach()
        self.recent_context = recent_context
        self.memory_store = memory_store
        self.fragment_providers = tuple(fragment_providers)
        self.persona_providers = tuple(persona_providers)
        self.recall_limit = max(0, recall_limit)
        self.recall_budget_chars = max(0, recall_budget_chars)
        self.recall_line_chars = max(40, recall_line_chars)

    def rebind(self, world: World) -> None:
        """Point the builder at a replacement world (e.g. after a live regeneration that
        swaps ``actor.world`` wholesale). The room-summary projection's observers are bound
        to a specific world, so attach a fresh projection to the new one rather than leaving
        stale observers on the discarded world."""
        if world is self.world:
            return
        self.world = world
        self.room_summary = RoomSummaryProjection(world).attach()

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
        visible_characters = tuple(
            self._label(e.name, e.id) for e in perception.entities if e.is_character
        )
        visible_objects = tuple(
            self._label(e.name, e.id) for e in perception.entities if not e.is_character
        )

        inventory, held, worn = self._equipment(character)
        feelings = (
            tuple(sorted(character.get_component(AffectComponent).labels))
            if character.has_component(AffectComponent)
            else ()
        )
        conditions: list[str] = []
        for provider in self.fragment_providers:
            conditions.extend(provider(self.world, character))
        persona = self._persona_facts(character, identity)
        for provider in self.persona_providers:
            persona.extend(provider(self.world, character))

        recent = ()
        if self.recent_context is not None and room_id is not None:
            recent = self.recent_context.recent(room_id)
        social_cues = self._social_cues(
            character,
            perception.entities,
            recent=tuple(recent),
        )

        notes = self._notes(character)
        recall = self._recall(
            character,
            location_title=location_title,
            visible_characters=visible_characters,
            visible_objects=visible_objects,
            recent=tuple(recent),
        )
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
            persona=tuple(dict.fromkeys(persona)),
            conditions=tuple(conditions),
            feelings=feelings,
            social_cues=social_cues,
            recent=tuple(recent),
            notes=notes,
            recall=recall,
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
                BehaviorControllerComponent,
                DiscordControllerComponent,
                LLMControllerComponent,
                MCPControllerComponent,
                ScriptedControllerComponent,
            )

            if controller.has_component(DiscordControllerComponent):
                kind = "controlled by a human"
            elif controller.has_component(LLMControllerComponent):
                kind = "controlled by an agent"
            elif controller.has_component(MCPControllerComponent):
                kind = "controlled by an MCP agent"
            elif controller.has_component(BehaviorControllerComponent):
                kind = "controlled by a behavior routine"
            elif controller.has_component(ScriptedControllerComponent):
                kind = "controlled by a scripted routine"
            else:
                kind = "suspended"
            break
        return f"{status}, {kind}"

    def _persona_facts(
        self, character: Entity, identity: IdentityComponent | None
    ) -> list[str]:
        name = identity.name if identity else "Unknown"
        kind = identity.kind if identity else "character"
        return [
            f"Your name is {name}.",
            f"Your kind is {kind}.",
            f"Your current status is {self._status_line(character)}.",
        ]

    def _label(self, name: str, entity_id: object) -> str:
        if self.include_entity_ids and entity_id is not None:
            return f"{name} [{entity_id}]"
        return name

    def _exit_label(self, exit_: RoomExit) -> str:
        direction = f"{exit_.direction} (locked)" if exit_.locked else exit_.direction
        return self._label(direction, exit_.to_room_id)

    def _equipment(
        self, character: Entity
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        inventory: list[str] = []
        for edge, child_id in character.get_relationships(Contains):
            del edge
            inventory.append(self._label(_name(self.world.get_entity(child_id)), child_id))
        held = [
            self._label(_name(self.world.get_entity(item_id)), item_id)
            for _edge, item_id in character.get_relationships(Holding)
        ]
        worn = [
            self._label(_name(self.world.get_entity(item_id)), item_id)
            for _edge, item_id in character.get_relationships(Wearing)
        ]
        return tuple(sorted(inventory)), tuple(sorted(held)), tuple(sorted(worn))

    def _notes(self, character: Entity) -> tuple[str, ...]:
        if self.memory_store is None or not character.has_component(MemoryProfileComponent):
            return ()
        collection = character.get_component(MemoryProfileComponent).vector_collection
        entries = self.memory_store.search(collection, mode="recent", limit=3)
        return tuple(entry.text for entry in entries)

    def _social_cues(
        self,
        character: Entity,
        visible_entities,
        *,
        recent: tuple[str, ...],
    ) -> tuple[str, ...]:
        self_name = _name(character)
        recent_lower = tuple(line.lower() for line in recent)
        last_speech = next((line for line in reversed(recent) if " said:" in line), "")
        cues: list[str] = []
        for perceived in visible_entities:
            if not perceived.is_character:
                continue
            name = perceived.name
            name_key = name.lower()
            if any(line.startswith(f"{name_key} arrived.") for line in recent_lower):
                cues.append(f"{name} just arrived.")
            if any(line.startswith(f"{name_key} left.") for line in recent_lower):
                cues.append(f"{name} just left.")
            if any(line.startswith(f"{name_key} said:") for line in recent_lower):
                cues.append(f"{name} just spoke.")
            entity_id = parse_entity_id(perceived.id)
            if entity_id is not None and self.world.has_entity(entity_id):
                entity = self.world.get_entity(entity_id)
                distress = self._distress_labels(entity)
                if entity.has_component(AffectComponent):
                    if distress:
                        cues.append(f"{name} seems {', '.join(distress)}.")
                bond = self._visible_bond(entity, character.id)
            else:
                distress = ()
                bond = None
            if last_speech.lower().startswith(f"{self_name.lower()} said:"):
                if self._is_pointed_silence(distress, bond):
                    cues.append(f"{name} is pointedly silent after what you said.")
                else:
                    cues.append(f"{name} has not answered you.")
            elif recent and not any(
                line.startswith(f"{name_key} said:") for line in recent_lower
            ):
                cues.append(f"{name} is quiet.")
                if self._is_brooding(distress):
                    cues.append(f"{name} is brooding silently.")
                elif self._is_watching(bond):
                    cues.append(f"{name} is watching you quietly.")
            elif not recent:
                if self._is_brooding(distress):
                    cues.append(f"{name} is brooding silently.")
                elif self._is_watching(bond):
                    cues.append(f"{name} is watching you quietly.")
        return tuple(dict.fromkeys(cues))

    @staticmethod
    def _distress_labels(entity: Entity) -> tuple[str, ...]:
        if not entity.has_component(AffectComponent):
            return ()
        return tuple(
            label
            for label in sorted(entity.get_component(AffectComponent).labels)
            if label in {"afraid", "angry", "sad", "tense", "unhappy"}
        )

    def _visible_bond(self, entity: Entity, viewer_id: EntityId):
        from ..mechanics.social import bond_between

        return bond_between(self.world, entity.id, viewer_id)

    @staticmethod
    def _is_pointed_silence(distress: tuple[str, ...], bond) -> bool:
        if bond is not None and (bond.resentment >= 0.3 or bond.fear >= 0.3):
            return True
        return any(label in {"angry", "tense", "unhappy"} for label in distress)

    @staticmethod
    def _is_brooding(distress: tuple[str, ...]) -> bool:
        return any(label in {"angry", "sad", "tense", "unhappy"} for label in distress)

    @staticmethod
    def _is_watching(bond) -> bool:
        if bond is None:
            return False
        return bond.familiarity >= 0.4 or bond.trust >= 0.3 or bond.affinity >= 0.4

    def _recall(
        self,
        character: Entity,
        *,
        location_title: str,
        visible_characters: tuple[str, ...],
        visible_objects: tuple[str, ...],
        recent: tuple[str, ...],
    ) -> tuple[str, ...]:
        if self.memory_store is None or not character.has_component(MemoryProfileComponent):
            return ()
        query = " ".join(
            value
            for value in (
                location_title,
                *visible_characters,
                *visible_objects,
                *recent,
            )
            if value
        )
        if not query.strip():
            return ()
        collection = character.get_component(MemoryProfileComponent).vector_collection
        entries = self.memory_store.search(
            collection, query=query, mode="keyword", limit=self.recall_limit
        )
        lines = (
            f"{self._truncate_memory(entry.text)} "
            f"[memory:{entry.id} source:{entry.source} score:{entry.score or 0.0:.1f}]"
            for entry in entries
        )
        return self._fit_memory_budget(lines)

    def _truncate_memory(self, text: str) -> str:
        if len(text) <= self.recall_line_chars:
            return text
        return text[: self.recall_line_chars - 3].rstrip() + "..."

    def _fit_memory_budget(self, lines) -> tuple[str, ...]:
        if self.recall_budget_chars <= 0:
            return ()
        kept: list[str] = []
        used = 0
        for line in lines:
            next_used = used + len(line)
            if kept:
                next_used += 1
            if next_used > self.recall_budget_chars:
                continue
            kept.append(line)
            used = next_used
        return tuple(kept)

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
        commands.append("forget note by id")
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
    section("Persona", context.persona)
    section("You feel", context.feelings)
    section("Currently", context.conditions)
    section("Social cues", context.social_cues)
    section("Recent context", context.recent)
    section("Notes", context.notes)
    section("Recall", context.recall)

    lines.append("Points:")
    lines.append(f"Action: {context.action[0]}/{context.action[1]}")
    lines.append(f"Focus: {context.focus[0]}/{context.focus[1]}")
    lines.append("")
    section("Available commands", context.commands)
    if context.warnings:
        section("Warnings", context.warnings)
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["PromptBuilder", "PromptContext", "render_prompt"]
