"""Structured world-generation proposal schema (spec 22).

The DM/world-builder proposes content as validated Pydantic models. It never touches the
Relics world directly; the engine validates the proposal and instantiates it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..llm_agents.agent import DEFAULT_MODEL


class RoomSpec(BaseModel):
    key: str
    title: str
    biome: str = "unknown"
    indoor: bool = False
    light: float | None = None
    celsius: float | None = None


class ExitSpec(BaseModel):
    from_key: str
    direction: str
    to_key: str
    locked: bool = False


class ObjectSpec(BaseModel):
    key: str
    room_key: str
    name: str
    kind: str = "item"  # item | food | water | container | paper | key | door
    portable: bool = True
    nutrition: float = 0.0
    satiety: float = 0.0
    hydration: float = 0.0
    renewable: bool = True
    open: bool = True
    writable: bool = False
    key_name: str | None = None
    locked: bool = False


class CharacterSpec(BaseModel):
    key: str
    name: str
    room_key: str
    species: str = "bunny"
    controller: str = "suspended"  # llm | suspended
    llm_profile: str = "default"
    llm_model: str = DEFAULT_MODEL
    with_needs: bool = True
    with_memory: bool = True
    traits: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()

    @field_validator("llm_profile", "llm_model", mode="before")
    @classmethod
    def _default_llm_fields(cls, value: object, info) -> object:
        if value is None:
            return cls.model_fields[info.field_name].default
        return value


class WorldProposal(BaseModel):
    seed: str
    rooms: list[RoomSpec] = Field(default_factory=list)
    exits: list[ExitSpec] = Field(default_factory=list)
    objects: list[ObjectSpec] = Field(default_factory=list)
    characters: list[CharacterSpec] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Incremental, graph-first generation (spec 22; recursive BFS path). These describe a
# single piece of the world at a time so the DM can be prompted node-by-node.
# --------------------------------------------------------------------------------------


class RoomNodeProposal(BaseModel):
    """A single room, without exits — those are proposed separately so BFS can drive them."""

    title: str
    biome: str = "unknown"
    indoor: bool = False
    light: float | None = None
    celsius: float | None = None
    description: str = ""  # short prose, re-shown to the DM when populating the room


class DoorProposal(BaseModel):
    """One outgoing connection from a room. The room behind it is generated on expansion."""

    direction: str
    bidirectional: bool = True  # False for slides, cliffs, one-way portals, etc.
    return_direction: str | None = None  # reverse direction if not the natural opposite
    locked: bool = False
    hidden: bool = False
    beyond_hint: str = ""  # hint to the DM about what lies on the other side


class DanglingResolution(BaseModel):
    """How to close a door left dangling when the room budget is reached."""

    action: Literal["seal", "drop", "link"] = "seal"
    target_room_key: str | None = None  # required for "link"


class ItemProposal(BaseModel):
    """An object inside a room, inventory, or container (room_key/key are generator-assigned)."""

    name: str
    kind: str = "item"
    portable: bool = True
    nutrition: float = 0.0
    satiety: float = 0.0
    hydration: float = 0.0
    renewable: bool = True
    open: bool = True
    writable: bool = False
    key_name: str | None = None
    locked: bool = False


class CharacterProposal(BaseModel):
    """A character inside a room (key/room are generator-assigned)."""

    name: str
    species: str = "bunny"
    controller: str = "suspended"  # llm | suspended
    llm_profile: str = "default"
    llm_model: str = DEFAULT_MODEL
    with_needs: bool = True
    with_memory: bool = True
    traits: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    key: str = ""  # assigned by the generator before instantiation

    @field_validator("llm_profile", "llm_model", mode="before")
    @classmethod
    def _default_llm_fields(cls, value: object, info) -> object:
        if value is None:
            return cls.model_fields[info.field_name].default
        return value


class RoomContentsProposal(BaseModel):
    objects: list[ItemProposal] = Field(default_factory=list)
    characters: list[CharacterProposal] = Field(default_factory=list)


class StoryEventProposal(BaseModel):
    """A room-scoped event/incident/encounter proposed by the DM."""

    title: str
    kind: str = "story_event"
    summary: str = ""
    severity: float = 1.0
    budget_spent: float = 0.0
    tags: tuple[str, ...] = ()
    stimulus_type: str = "story_event"
    stimulus_intensity: float = 1.0
    objects: list[ItemProposal] = Field(default_factory=list)
    characters: list[CharacterProposal] = Field(default_factory=list)


__all__ = [
    "CharacterProposal",
    "CharacterSpec",
    "DanglingResolution",
    "DoorProposal",
    "ExitSpec",
    "ItemProposal",
    "ObjectSpec",
    "RoomContentsProposal",
    "RoomNodeProposal",
    "RoomSpec",
    "StoryEventProposal",
    "WorldProposal",
]
