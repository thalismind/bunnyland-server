"""Structured world-generation proposal schema (spec 22).

The DM/world-builder proposes content as validated Pydantic models. It never touches the
Relics world directly; the engine validates the proposal and instantiates it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.components import GenerationIntentComponent
from ..llm_agents.agent import DEFAULT_MODEL

_SEVERITY_LABELS = {
    "none": 0.0,
    "trivial": 0.5,
    "minor": 1.0,
    "low": 1.0,
    "moderate": 2.0,
    "medium": 2.0,
    "high": 3.0,
    "major": 4.0,
    "severe": 5.0,
    "critical": 5.0,
}

_LIGHT_LABELS = {
    "dark": 0.0,
    "dim": 0.25,
    "low": 0.3,
    "soft": 0.45,
    "medium": 0.5,
    "moderate": 0.5,
    "fluorescent": 0.7,
    "artificial": 0.7,
    "bright": 0.85,
    "sunny": 0.95,
}

_CELSIUS_LABELS = {
    "freezing": -5.0,
    "cold": 5.0,
    "cool": 12.0,
    "room temperature": 21.0,
    "temperate": 21.0,
    "warm": 27.0,
    "hot": 35.0,
}


def _coerce_profile_string(value: object, default: str) -> object:
    if value is None:
        return default
    if isinstance(value, Mapping):
        for key in ("profile", "profile_name", "id", "name"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested
        return default
    return value


def _coerce_numeric_label(value: object) -> object:
    if isinstance(value, str):
        return _SEVERITY_LABELS.get(value.strip().lower(), value)
    return value


def _coerce_float_or_label(value: object, labels: Mapping[str, float]) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip().lower()
    try:
        return float(text)
    except ValueError:
        return labels.get(text, None)


def _default_if_none(value: object, default: object) -> object:
    return default if value is None else value


def _generation_dict(value: object) -> dict[str, object]:
    if isinstance(value, GenerationIntentComponent):
        return {
            "description": value.description,
            "tags": value.tags,
            "wants": value.wants,
            "needs": value.needs,
            "source_seed": value.source_seed,
            "source_key": value.source_key,
            "entity_kind": value.entity_kind,
            "unmet_capabilities": value.unmet_capabilities,
        }
    if isinstance(value, Mapping):
        return dict(value)
    return {}


class _GenerationIntentModel(BaseModel):
    generation: GenerationIntentComponent = Field(default_factory=GenerationIntentComponent)

    @model_validator(mode="before")
    @classmethod
    def _coerce_generation_intent(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        generation = _generation_dict(
            data.pop("generation", data.pop("generation_intent", {}))
        )
        if "intent" in data and "description" not in generation:
            generation["description"] = data.pop("intent")
        for key in ("description", "tags", "wants", "needs"):
            if key in data:
                generation[key] = data.pop(key)
        if generation:
            data["generation"] = generation
        return data

    @property
    def description(self) -> str:
        return self.generation.description

    @property
    def tags(self) -> tuple[str, ...]:
        return self.generation.tags

    @property
    def wants(self) -> tuple[str, ...]:
        return self.generation.wants

    @property
    def needs(self) -> tuple[str, ...]:
        return self.generation.needs


class RoomSpec(_GenerationIntentModel):
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


class ObjectSpec(_GenerationIntentModel):
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

    @field_validator(
        "portable",
        "nutrition",
        "satiety",
        "hydration",
        "renewable",
        "open",
        "writable",
        "locked",
        mode="before",
    )
    @classmethod
    def _default_null_scalars(cls, value: object, info) -> object:
        return _default_if_none(value, cls.model_fields[info.field_name].default)


class CharacterSpec(_GenerationIntentModel):
    key: str
    name: str
    room_key: str
    species: str = "bunny"
    controller: str = "suspended"  # llm | suspended | behavioral | scripted
    llm_profile: str = "default"
    llm_model: str = DEFAULT_MODEL
    llm_provider: str = "ollama"
    behavior_name: str = "idle"  # behavior-tree name when controller == "behavioral"
    script_name: str = ""  # script name when controller == "scripted"
    script_loop: bool = False  # replay the script in a loop when controller == "scripted"
    with_needs: bool = True
    with_memory: bool = True
    traits: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()

    @field_validator("llm_profile", "llm_model", "llm_provider", mode="before")
    @classmethod
    def _default_llm_fields(cls, value: object, info) -> object:
        return _coerce_profile_string(value, cls.model_fields[info.field_name].default)


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


class RoomNodeProposal(_GenerationIntentModel):
    """A single room, without exits — those are proposed separately so BFS can drive them."""

    title: str
    biome: str = "unknown"
    indoor: bool = False
    light: float | None = None
    celsius: float | None = None

    @field_validator("light", mode="before")
    @classmethod
    def _coerce_light_label(cls, value: object) -> object:
        return _coerce_float_or_label(value, _LIGHT_LABELS)

    @field_validator("celsius", mode="before")
    @classmethod
    def _coerce_celsius_label(cls, value: object) -> object:
        return _coerce_float_or_label(value, _CELSIUS_LABELS)


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


class ItemProposal(_GenerationIntentModel):
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

    @field_validator(
        "portable",
        "nutrition",
        "satiety",
        "hydration",
        "renewable",
        "open",
        "writable",
        "locked",
        mode="before",
    )
    @classmethod
    def _default_null_scalars(cls, value: object, info) -> object:
        return _default_if_none(value, cls.model_fields[info.field_name].default)


class CharacterProposal(_GenerationIntentModel):
    """A character inside a room (key/room are generator-assigned)."""

    name: str
    species: str = "bunny"
    controller: str = "suspended"  # llm | suspended | behavioral | scripted
    llm_profile: str = "default"
    llm_model: str = DEFAULT_MODEL
    llm_provider: str = "ollama"
    behavior_name: str = "idle"  # behavior-tree name when controller == "behavioral"
    script_name: str = ""  # script name when controller == "scripted"
    script_loop: bool = False  # replay the script in a loop when controller == "scripted"
    with_needs: bool = True
    with_memory: bool = True
    traits: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    key: str = ""  # assigned by the generator before instantiation

    @field_validator("llm_profile", "llm_model", "llm_provider", mode="before")
    @classmethod
    def _default_llm_fields(cls, value: object, info) -> object:
        return _coerce_profile_string(value, cls.model_fields[info.field_name].default)


class RoomContentsProposal(BaseModel):
    objects: list[ItemProposal] = Field(default_factory=list)
    characters: list[CharacterProposal] = Field(default_factory=list)


class StoryEventProposal(_GenerationIntentModel):
    """A room-scoped event/incident/encounter proposed by the DM."""

    title: str
    kind: str = "story_event"
    summary: str = ""
    severity: float = 1.0
    budget_spent: float = 0.0
    stimulus_type: str = "story_event"
    stimulus_intensity: float = 1.0
    objects: list[ItemProposal] = Field(default_factory=list)
    characters: list[CharacterProposal] = Field(default_factory=list)

    @field_validator("severity", "budget_spent", "stimulus_intensity", mode="before")
    @classmethod
    def _coerce_numeric_labels(cls, value: object) -> object:
        return _coerce_numeric_label(value)


__all__ = [
    "CharacterProposal",
    "CharacterSpec",
    "DanglingResolution",
    "DoorProposal",
    "ExitSpec",
    "GenerationIntentComponent",
    "ItemProposal",
    "ObjectSpec",
    "RoomContentsProposal",
    "RoomNodeProposal",
    "RoomSpec",
    "StoryEventProposal",
    "WorldProposal",
]
