"""Pydantic models for the optional HTTP API."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..content import ContentLibrary
from ..core.claim_timeout import CLAIM_TIMEOUT_MAX_SECONDS, CLAIM_TIMEOUT_MIN_SECONDS
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


class RecentEventsResponse(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


class QueuedCommandView(BaseModel):
    command_id: str
    character_id: str
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    cost: CommandCostRequest = Field(default_factory=CommandCostRequest)
    lane: Lane = Lane.WORLD
    submitted_at_epoch: int
    expires_at_epoch: int | None = None


class CharacterQueuedCommandsResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    character_id: str
    commands: list[QueuedCommandView] = Field(default_factory=list)


class ClientEntityView(BaseModel):
    id: str
    name: str
    kind: str = "other"
    is_character: bool = False
    contents: list[ClientEntityView] = Field(default_factory=list)


class ClientExitView(BaseModel):
    id: str
    direction: str
    label: str
    locked: bool = False


class ClientPointsView(BaseModel):
    action: float = 0.0
    action_max: float = 0.0
    focus: float = 0.0
    focus_max: float = 0.0


class ClientControllerView(BaseModel):
    controller_id: str
    generation: int


class ClientTargetView(BaseModel):
    id: str
    label: str
    kind: str = "other"


class ClientActionArgumentView(BaseModel):
    key: str
    title: str = ""
    kind: str = "string"
    required: bool = False
    target_group: str | None = None


class ClientActionView(BaseModel):
    command_type: str
    tool_name: str
    title: str
    description: str = ""
    lane: Lane = Lane.WORLD
    cost: CommandCostRequest = Field(default_factory=CommandCostRequest)
    arguments: list[ClientActionArgumentView] = Field(default_factory=list)


class ClientRoomView(BaseModel):
    id: str | None = None
    title: str = ""
    entities: list[ClientEntityView] = Field(default_factory=list)
    exits: list[ClientExitView] = Field(default_factory=list)


class ClientSpritePositionView(BaseModel):
    x: float = 0.0
    y: float = 0.0


class ClientSpriteBoundsView(BaseModel):
    width: float = 4.0
    height: float = 4.0
    solid: bool = False


class ClientSpriteView(BaseModel):
    position: ClientSpritePositionView = Field(default_factory=ClientSpritePositionView)
    image_url: str = ""
    image_data: str = ""
    layer: int = 20
    scale: float = 1.0
    bounds: ClientSpriteBoundsView = Field(default_factory=ClientSpriteBoundsView)
    emoji: str = ""


class RoomProjectionEntityView(BaseModel):
    id: str
    name: str
    kind: str = "other"
    is_character: bool = False
    sprite: ClientSpriteView = Field(default_factory=ClientSpriteView)


class RoomProjectionRoomView(BaseModel):
    id: str
    title: str = ""
    default_start: bool = False
    sprite: ClientSpriteView = Field(default_factory=ClientSpriteView)
    entities: list[RoomProjectionEntityView] = Field(default_factory=list)
    exits: list[ClientExitView] = Field(default_factory=list)


class RoomProjectionResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    room: RoomProjectionRoomView


class CharacterProjectionResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    character_id: str
    character_name: str
    can_perceive: bool
    room: ClientRoomView = Field(default_factory=ClientRoomView)
    inventory: list[ClientTargetView] = Field(default_factory=list)
    points: ClientPointsView = Field(default_factory=ClientPointsView)
    controller: ClientControllerView | None = None
    target_groups: dict[str, list[ClientTargetView]] = Field(default_factory=dict)
    actions: list[ClientActionView] = Field(default_factory=list)


class DmRoomProjectionView(BaseModel):
    id: str
    title: str
    biome: str = "unknown"
    occupants: list[ClientTargetView] = Field(default_factory=list)
    objects: list[ClientEntityView] = Field(default_factory=list)
    exits: list[ClientExitView] = Field(default_factory=list)


class DmProjectionResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    dm_id: str
    rooms: list[DmRoomProjectionView] = Field(default_factory=list)
    characters: list[ClientTargetView] = Field(default_factory=list)


class WorldLibraryResponse(ContentLibrary):
    pass


ClaimFallbackController = Literal["suspend", "llm"]


class WebControllerFallbackRequest(BaseModel):
    character_id: str
    client_id: str = Field(min_length=1)
    fallback_controller: ClaimFallbackController | None = None
    fallback_reason: str | None = None
    llm_profile_name: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    timeout_seconds: int | None = Field(
        default=None, ge=CLAIM_TIMEOUT_MIN_SECONDS, le=CLAIM_TIMEOUT_MAX_SECONDS
    )


class WebControllerClaimRequest(WebControllerFallbackRequest):
    label: str = "web"


class WebControllerFallbackResponse(BaseModel):
    ok: bool = True
    character_id: str
    controller_id: str
    controller_generation: int
    fallback_controller: str
    timeout_seconds: int


class WebControllerClaimResponse(WebControllerFallbackResponse):
    pass


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
    group: str = "custom"


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
    "ClientActionArgumentView",
    "ClientActionView",
    "CharacterProjectionResponse",
    "CharacterQueuedCommandsResponse",
    "ClientControllerView",
    "ClientEntityView",
    "ClientExitView",
    "ClientPointsView",
    "ClientRoomView",
    "ClientSpriteBoundsView",
    "ClientSpritePositionView",
    "ClientSpriteView",
    "ClientTargetView",
    "DmProjectionResponse",
    "DmRoomProjectionView",
    "QueuedCommandView",
    "RecentEventsResponse",
    "RoomProjectionEntityView",
    "RoomProjectionResponse",
    "RoomProjectionRoomView",
    "ComponentPatchSpec",
    "EcsTypeSchema",
    "EdgePatchSpec",
    "ClaimFallbackController",
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
    "WorldLibraryResponse",
    "WorldRoomGenerationRequest",
    "WorldRoomGenerationResponse",
    "WorldPatchRequest",
    "WorldPatchResponse",
    "WorldRuntimeResponse",
    "WorldSaveResponse",
    "WorldSchemaResponse",
    "WebControllerClaimRequest",
    "WebControllerClaimResponse",
    "WebControllerFallbackRequest",
    "WebControllerFallbackResponse",
]
