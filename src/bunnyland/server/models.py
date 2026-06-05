"""Pydantic models for the optional HTTP API."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..core.commands import CommandCost, Lane, OnInsufficientPoints, SubmittedCommand


class CommandCostRequest(BaseModel):
    action: int = 0
    focus: int = 0


class CommandRequest(BaseModel):
    character_id: str
    controller_id: str
    controller_generation: int
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    cost: CommandCostRequest = Field(default_factory=CommandCostRequest)
    lane: Lane = Lane.WORLD
    on_insufficient_points: OnInsufficientPoints = OnInsufficientPoints.QUEUE
    expires_at_epoch: int | None = None
    command_id: str | None = None

    def to_submitted(self, *, submitted_at_epoch: int) -> SubmittedCommand:
        return SubmittedCommand(
            command_id=self.command_id or uuid4().hex,
            character_id=self.character_id,
            controller_id=self.controller_id,
            controller_generation=self.controller_generation,
            command_type=self.command_type,
            payload=dict(self.payload),
            cost=CommandCost(action=self.cost.action, focus=self.cost.focus),
            lane=self.lane,
            on_insufficient_points=self.on_insufficient_points,
            submitted_at_epoch=submitted_at_epoch,
            expires_at_epoch=self.expires_at_epoch,
        )


class CommandResponse(BaseModel):
    queued: bool
    command_id: str


class ComponentPatchSpec(BaseModel):
    type: str
    fields: dict[str, Any] = Field(default_factory=dict)


class EdgePatchSpec(BaseModel):
    type: str
    fields: dict[str, Any] = Field(default_factory=dict)


class AddEntityPatchRequest(BaseModel):
    op: Literal["add_entity"]
    client_id: str | None = None
    prefab: str = "entity"
    components: list[ComponentPatchSpec] = Field(default_factory=list)


class DeleteEntityPatchRequest(BaseModel):
    op: Literal["delete_entity"]
    entity_id: str


class AddComponentPatchRequest(BaseModel):
    op: Literal["add_component"]
    entity_id: str
    component: ComponentPatchSpec


class SetComponentPatchRequest(BaseModel):
    op: Literal["set_component"]
    entity_id: str
    component: ComponentPatchSpec


class RemoveComponentPatchRequest(BaseModel):
    op: Literal["remove_component"]
    entity_id: str
    component_type: str


class SetEdgePatchRequest(BaseModel):
    op: Literal["set_edge"]
    source_id: str
    target_id: str
    edge: EdgePatchSpec


class RemoveEdgePatchRequest(BaseModel):
    op: Literal["remove_edge"]
    source_id: str
    target_id: str
    edge_type: str


WorldPatchOperation = Annotated[
    AddEntityPatchRequest
    | DeleteEntityPatchRequest
    | AddComponentPatchRequest
    | SetComponentPatchRequest
    | RemoveComponentPatchRequest
    | SetEdgePatchRequest
    | RemoveEdgePatchRequest,
    Field(discriminator="op"),
]


class WorldPatchRequest(BaseModel):
    operations: list[WorldPatchOperation] = Field(default_factory=list)


class WorldRoomGenerationRequest(BaseModel):
    door_entity_id: str
    direction: str | None = None
    prompt: str = ""


class WorldCharacterGenerationRequest(BaseModel):
    room_entity_id: str
    prompt: str = ""


class WorldItemGenerationRequest(BaseModel):
    container_entity_id: str
    prompt: str = ""


class WorldEventGenerationRequest(BaseModel):
    room_entity_id: str
    prompt: str = ""


class WorldGeneratorInfo(BaseModel):
    name: str
    description: str = ""
    uses_seed: bool = True


class WorldGeneratorListResponse(BaseModel):
    ok: bool = True
    generators: list[WorldGeneratorInfo] = Field(default_factory=list)


class WorldGenerateRequest(BaseModel):
    seed: str | None = None
    generator: str | None = None
    max_rooms: int | None = Field(default=None, ge=1)
    confirm_reset: bool = False
    save: bool = False


class WorldPatchResponse(BaseModel):
    ok: bool = True
    world_epoch: int
    changed_entities: list[dict[str, Any]] = Field(default_factory=list)
    deleted_entities: list[str] = Field(default_factory=list)


class WorldRoomGenerationResponse(BaseModel):
    ok: bool = True
    source_room_id: str
    door_entity_id: str
    generated_title: str
    patch: WorldPatchRequest


class WorldCharacterGenerationResponse(BaseModel):
    ok: bool = True
    room_entity_id: str
    generated_name: str
    patch: WorldPatchRequest


class WorldItemGenerationResponse(BaseModel):
    ok: bool = True
    container_entity_id: str
    generated_name: str
    patch: WorldPatchRequest


class WorldEventGenerationResponse(BaseModel):
    ok: bool = True
    room_entity_id: str
    generated_title: str
    generated_kind: str
    patch: WorldPatchRequest


class WorldSaveResponse(BaseModel):
    ok: bool = True
    path: str
    world_epoch: int
    saved_at_epoch: int
    saved_at: str | None = None


class WorldGenerateResponse(BaseModel):
    ok: bool = True
    job_id: str
    status: str
    seed: str
    generator: str
    world_epoch: int


class WorldGenerationStatusResponse(BaseModel):
    ok: bool = True
    job_id: str | None = None
    status: str = "idle"
    seed: str | None = None
    generator: str | None = None
    world_epoch: int
    rooms: int = 0
    characters: int = 0
    error: str | None = None
    saved: WorldSaveResponse | None = None


class WorldRuntimeResponse(BaseModel):
    ok: bool = True
    world_epoch: int
    paused: bool
    running: bool


class EcsTypeSchema(BaseModel):
    name: str
    module: str
    qualname: str
    json_schema: dict[str, Any]
    used: bool = False
    count: int = 0
    schema_error: str | None = None


class WorldSchemaResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    components: dict[str, EcsTypeSchema] = Field(default_factory=dict)
    edges: dict[str, EcsTypeSchema] = Field(default_factory=dict)


__all__ = [
    "CommandCostRequest",
    "CommandRequest",
    "CommandResponse",
    "ComponentPatchSpec",
    "EcsTypeSchema",
    "EdgePatchSpec",
    "WorldCharacterGenerationRequest",
    "WorldCharacterGenerationResponse",
    "WorldEventGenerationRequest",
    "WorldEventGenerationResponse",
    "WorldGenerateRequest",
    "WorldGenerateResponse",
    "WorldGenerationStatusResponse",
    "WorldGeneratorInfo",
    "WorldGeneratorListResponse",
    "WorldItemGenerationRequest",
    "WorldItemGenerationResponse",
    "WorldRoomGenerationRequest",
    "WorldRoomGenerationResponse",
    "WorldPatchRequest",
    "WorldPatchResponse",
    "WorldRuntimeResponse",
    "WorldSaveResponse",
    "WorldSchemaResponse",
]
