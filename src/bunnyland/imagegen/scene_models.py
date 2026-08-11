"""Typed, durable visual context shared by image and video prompt generation."""

from __future__ import annotations

from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict
from relics import Entity, World

MAX_SCENE_CONTEXT_CHARS: Final = 32_000


class MediaFact(BaseModel):
    """One public visual fact contributed by core or a plugin."""

    model_config = ConfigDict(frozen=True)

    id: str
    category: str
    text: str
    entity_id: str = ""


class MediaPosition(BaseModel):
    """Optional toon-space placement used as composition guidance."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    layer: int = 0


class MediaEntitySnapshot(BaseModel):
    """Public visual description of one character or object."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    kind: str = ""
    role: str = "background"
    description: str = ""
    appearance: str = ""
    species: str = ""
    biography: str = ""
    tags: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    held: tuple[str, ...] = ()
    worn: tuple[str, ...] = ()
    position: MediaPosition | None = None
    facts: tuple[MediaFact, ...] = ()


class MediaRoomSnapshot(BaseModel):
    """Stable visual identity and environmental state of the rendered room."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    description: str = ""
    appearance: str = ""
    biome: str = "unknown"
    region: str = ""
    indoor: bool = False
    light: str = ""
    temperature: str = ""
    time_of_day: str = ""
    weather: str = ""
    facts: tuple[MediaFact, ...] = ()


class MediaEventSnapshot(BaseModel):
    """One public event retained as foreground or temporal lead-in context."""

    model_config = ConfigDict(frozen=True)

    id: str
    event_type: str
    summary: str
    epoch: int
    actor_id: str = ""
    target_ids: tuple[str, ...] = ()
    causation_id: str = ""
    correlation_id: str = ""
    details: tuple[str, ...] = ()


class MediaSceneSnapshot(BaseModel):
    """Versioned public scene context persisted for deterministic regeneration."""

    model_config = ConfigDict(frozen=True)

    version: int = 1
    captured_at_epoch: int
    viewer_id: str
    primary_event_id: str = ""
    world_title: str = ""
    world_description: str = ""
    room: MediaRoomSnapshot
    characters: tuple[MediaEntitySnapshot, ...] = ()
    objects: tuple[MediaEntitySnapshot, ...] = ()
    events: tuple[MediaEventSnapshot, ...] = ()

    def prompt_context(self) -> str:
        """Return bounded structured JSON for an LLM prompt."""

        rendered = self.model_dump_json()
        if len(rendered) <= MAX_SCENE_CONTEXT_CHARS:
            return rendered
        primary = next(
            (event for event in self.events if event.id == self.primary_event_id),
            self.events[-1] if self.events else None,
        )
        character = self.characters[0] if self.characters else None
        bounded = MediaSceneSnapshot(
            captured_at_epoch=self.captured_at_epoch,
            viewer_id=self.viewer_id[:500],
            primary_event_id=self.primary_event_id[:500],
            world_title=self.world_title[:500],
            world_description=self.world_description[:2_000],
            room=MediaRoomSnapshot(
                id=self.room.id[:500],
                title=self.room.title[:500],
                description=self.room.description[:2_000],
                appearance=self.room.appearance[:2_000],
                biome=self.room.biome[:500],
                region=self.room.region[:500],
                indoor=self.room.indoor,
                light=self.room.light[:500],
                temperature=self.room.temperature[:500],
                time_of_day=self.room.time_of_day[:500],
                weather=self.room.weather[:500],
            ),
            characters=(
                character.model_copy(
                    update={
                        "name": character.name[:500],
                        "description": character.description[:2_000],
                        "appearance": character.appearance[:2_000],
                        "biography": character.biography[:2_000],
                        "tags": tuple(tag[:80] for tag in character.tags[:32]),
                        "facts": (),
                    }
                ),
            )
            if character is not None
            else (),
            events=(
                primary.model_copy(
                    update={
                        "id": primary.id[:500],
                        "event_type": primary.event_type[:500],
                        "summary": primary.summary[:2_000],
                        "actor_id": primary.actor_id[:500],
                        "target_ids": tuple(
                            target_id[:500] for target_id in primary.target_ids[:16]
                        ),
                        "causation_id": primary.causation_id[:500],
                        "correlation_id": primary.correlation_id[:500],
                        "details": (),
                    }
                ),
            )
            if primary is not None
            else (),
        )
        return bounded.model_dump_json()


class MediaFactRequest(BaseModel):
    """Context supplied to plugin media-fact providers."""

    model_config = ConfigDict(frozen=True)

    role: str
    viewer_id: str
    primary_event_id: str = ""


@runtime_checkable
class MediaFactProvider(Protocol):
    """Adds public visual facts for an entity selected by the core projection."""

    def facts_for(
        self,
        world: World,
        entity: Entity,
        request: MediaFactRequest,
    ) -> tuple[MediaFact, ...]: ...


__all__ = [
    "MAX_SCENE_CONTEXT_CHARS",
    "MediaEntitySnapshot",
    "MediaEventSnapshot",
    "MediaFact",
    "MediaFactProvider",
    "MediaFactRequest",
    "MediaPosition",
    "MediaRoomSnapshot",
    "MediaSceneSnapshot",
]
