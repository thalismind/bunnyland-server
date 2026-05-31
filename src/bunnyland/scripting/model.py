"""JSON-serializable script definitions.

Scripts are external content: plugins or standalone JSON files provide them, and the
runtime keeps execution state outside the ECS world. The schema intentionally stays small
so it can back both fixture files and a later block editor.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.commands import Lane, OnInsufficientPoints


class ExecutionPolicy(StrEnum):
    ONCE = "once"
    ALWAYS = "always"


class FanoutMode(StrEnum):
    ONE = "one"
    FIRST = "first"
    EACH = "each"


class EntityQuery(BaseModel):
    """A deterministic entity selector.

    Component names use class names, e.g. ``CharacterComponent``. ``in_room`` accepts an
    entity id or binding reference such as ``"$garden"``.
    """

    model_config = ConfigDict(frozen=True)

    id: str | None = None
    components: tuple[str, ...] = ()
    without_components: tuple[str, ...] = ()
    identity_name: str | None = None
    identity_kind: str | None = None
    tags: tuple[str, ...] = ()
    room_title: str | None = None
    in_room: str | None = None
    controller_kind: Literal["discord", "llm", "suspended", "unknown"] | None = None


class TargetSelector(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: EntityQuery
    mode: FanoutMode = FanoutMode.ONE
    bind: str = "actor"


class Trigger(BaseModel):
    """Composable trigger predicate.

    ``all`` and ``any`` nest other trigger predicates. Leaf predicates currently cover
    tick/epoch checks and domain event matching.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    all: tuple[Trigger, ...] = ()
    any: tuple[Trigger, ...] = ()
    not_: Trigger | None = Field(default=None, alias="not")
    tick: bool = False
    epoch_at_least: int | None = None
    event_type: str | None = None
    event_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _has_predicate(self) -> Trigger:
        if (
            not self.all
            and not self.any
            and self.not_ is None
            and not self.tick
            and self.epoch_at_least is None
            and self.event_type is None
        ):
            raise ValueError("trigger must define a predicate")
        return self


class CommandCostSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: int = 0
    focus: int = 0


class SubmitCommandAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["submit_command"] = "submit_command"
    target: TargetSelector
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    cost: CommandCostSpec = Field(default_factory=CommandCostSpec)
    lane: Lane = Lane.WORLD
    on_insufficient_points: OnInsufficientPoints = OnInsufficientPoints.QUEUE
    expires_after_seconds: int | None = None


class ComponentSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    fields: dict[str, Any] = Field(default_factory=dict)


class AddEntityPatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    op: Literal["add_entity"] = "add_entity"
    bind: str | None = None
    components: tuple[ComponentSpec, ...] = ()
    contain_in: EntityQuery | None = None
    containment_mode: str = "room_content"


class AddComponentPatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    op: Literal["add_component"] = "add_component"
    target: TargetSelector
    component: ComponentSpec


class SetComponentFieldsPatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    op: Literal["set_component_fields"] = "set_component_fields"
    target: TargetSelector
    component_type: str
    fields: dict[str, Any]


PatchOperation = Annotated[
    AddEntityPatch | AddComponentPatch | SetComponentFieldsPatch,
    Field(discriminator="op"),
]


class PatchWorldAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["patch_world"] = "patch_world"
    operations: tuple[PatchOperation, ...] = ()


ScriptAction = Annotated[
    SubmitCommandAction | PatchWorldAction,
    Field(discriminator="kind"),
]


class ScriptBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    trigger: Trigger
    actions: tuple[ScriptAction, ...] = ()
    priority: int = 0
    execution: ExecutionPolicy = ExecutionPolicy.ONCE
    cooldown_seconds: int = 0


class ScriptDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str = ""
    version: str = "0.1.0"
    blocks: tuple[ScriptBlock, ...] = ()
    bindings: dict[str, str] = Field(default_factory=dict)


class ScriptBlockState(BaseModel):
    count: int = 0
    last_fired_epoch: int | None = None


class ScriptState(BaseModel):
    blocks: dict[str, ScriptBlockState] = Field(default_factory=dict)


__all__ = [
    "AddComponentPatch",
    "AddEntityPatch",
    "CommandCostSpec",
    "ComponentSpec",
    "EntityQuery",
    "ExecutionPolicy",
    "FanoutMode",
    "PatchOperation",
    "PatchWorldAction",
    "ScriptAction",
    "ScriptBlock",
    "ScriptBlockState",
    "ScriptDefinition",
    "ScriptState",
    "SetComponentFieldsPatch",
    "SubmitCommandAction",
    "TargetSelector",
    "Trigger",
]
