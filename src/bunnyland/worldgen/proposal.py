"""Structured world-generation proposal schema (spec 22).

The DM/world-builder proposes content as validated Pydantic models. It never touches the
Relics world directly; the engine validates the proposal and instantiates it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    llm_model: str = "llama3"
    with_needs: bool = True
    with_memory: bool = True


class WorldProposal(BaseModel):
    seed: str
    rooms: list[RoomSpec] = Field(default_factory=list)
    exits: list[ExitSpec] = Field(default_factory=list)
    objects: list[ObjectSpec] = Field(default_factory=list)
    characters: list[CharacterSpec] = Field(default_factory=list)


__all__ = [
    "CharacterSpec",
    "ExitSpec",
    "ObjectSpec",
    "RoomSpec",
    "WorldProposal",
]
