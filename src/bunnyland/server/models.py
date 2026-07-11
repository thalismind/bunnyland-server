"""Pydantic models for the optional HTTP API."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..content import ContentLibrary
from ..core.claim_timeout import CLAIM_TIMEOUT_MAX_SECONDS, CLAIM_TIMEOUT_MIN_SECONDS
from ..core.commands import CommandCost, Lane, OnInsufficientPoints, SubmittedCommand

#: Upper bound for client-supplied free-form identifiers/labels (client_id, controller
#: label). Caps unbounded strings that would otherwise be stored or echoed, without
#: constraining legitimate values (UUID client ids and short labels are well under this).
IDENTIFIER_MAX_LENGTH = 128


class CommandCostRequest(BaseModel):
    action: int = 0
    focus: int = 0


class CommandRequest(BaseModel):
    character_id: str
    controller_id: str
    controller_generation: int
    claim_id: str | None = None
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
    reason: str = ""


class CommandCancelResponse(BaseModel):
    ok: bool
    command_id: str
    cancelled: bool
    reason: str = ""


class RecentEventsResponse(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


class FeatureStatusResponse(BaseModel):
    mcp: bool = False
    character_chat: bool = False
    character_sheets: bool = True
    image_generation: bool = False


class CharacterChatStatusResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    enabled: bool = False
    allowed_tools: list[str] = Field(default_factory=list)


class CharacterChatHistoryMessage(BaseModel):
    role: Literal["user", "character"]
    text: str = Field(min_length=1, max_length=4000)


class CharacterChatRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_LENGTH)
    claim_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    history_summary: str = Field(default="", max_length=12000)
    history: list[CharacterChatHistoryMessage] = Field(default_factory=list, max_length=24)


class CharacterChatActionResult(BaseModel):
    tool: str | None = None
    command_id: str | None = None
    status: Literal["none", "queued", "executed", "rejected", "unresolved", "failed"] = "none"
    reason: str = ""
    result_events: list[dict[str, Any]] = Field(default_factory=list)


class CharacterChatResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    character_id: str
    reply: str
    action: CharacterChatActionResult = Field(default_factory=CharacterChatActionResult)


class CharacterChatPendingResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    character_id: str
    command_id: str
    complete: bool = False
    reply: str = ""
    action: CharacterChatActionResult = Field(default_factory=CharacterChatActionResult)


class ControllerAssignmentRequest(BaseModel):
    character_id: str
    controller_id: str


class HealthResponse(BaseModel):
    ok: bool = True
    world_epoch: int
    git_hash: str = "unknown"
    features: FeatureStatusResponse = Field(default_factory=FeatureStatusResponse)


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
    generated_at_unix: float | None = None
    next_tick_at_unix: float | None = None
    tick_seconds: float | None = None
    time_scale: float | None = None
    game_seconds_per_tick: float | None = None
    commands: list[QueuedCommandView] = Field(default_factory=list)


class CharacterSummaryView(BaseModel):
    """A claim-lobby entry: enough to list and pick a character, never their state."""

    character_id: str
    name: str
    kind: str = "character"
    suspended: bool = False


class CharacterListResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    characters: list[CharacterSummaryView] = Field(default_factory=list)


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
    kind: str = ""
    name: str = ""
    detail: str = ""


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
    icon: str = ""
    lane: Lane = Lane.WORLD
    cost: CommandCostRequest = Field(default_factory=CommandCostRequest)
    arguments: list[ClientActionArgumentView] = Field(default_factory=list)
    natural_patterns: list[dict[str, Any]] = Field(default_factory=list)
    # Per-character availability (character projection only; defaults keep the
    # character-agnostic action search backward compatible).
    available: bool = True
    enough_action_points: bool = True
    enough_focus_points: bool = True
    has_required_target: bool = True
    meets_requirements: bool = True
    unavailable_reason: str = ""


class ClientRoomView(BaseModel):
    id: str | None = None
    title: str = ""
    entities: list[ClientEntityView] = Field(default_factory=list)
    exits: list[ClientExitView] = Field(default_factory=list)


class ClientSheetMetricView(BaseModel):
    label: str
    value: float
    maximum: float | None = None
    text: str = ""
    band: str = ""


class ClientSheetEntryView(BaseModel):
    label: str
    value: str = ""
    detail: str = ""


class ClientCharacterSheetView(BaseModel):
    kind: str = "character"
    species: str = ""
    biography: str = ""
    description: str = ""
    appearance: str = ""
    tags: list[str] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    vitals: list[ClientSheetMetricView] = Field(default_factory=list)
    needs: list[ClientSheetMetricView] = Field(default_factory=list)
    affect: list[ClientSheetMetricView] = Field(default_factory=list)
    profile: list[ClientSheetEntryView] = Field(default_factory=list)
    skills: list[ClientSheetEntryView] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    relations: list[ClientSheetEntryView] = Field(default_factory=list)
    injuries: list[ClientSheetEntryView] = Field(default_factory=list)
    notes: list[ClientSheetEntryView] = Field(default_factory=list)


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


class ClientImageView(BaseModel):
    url: str = ""
    alpha_url: str = ""


class CharacterImageUploadResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    character_id: str
    purpose: str
    url: str
    content_type: str


class RoomProjectionEntityView(BaseModel):
    id: str
    name: str
    kind: str = "other"
    is_character: bool = False
    sprite: ClientSpriteView = Field(default_factory=ClientSpriteView)
    portrait: ClientImageView = Field(default_factory=ClientImageView)


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


class WorldOverviewRoomView(BaseModel):
    id: str
    title: str = ""
    biome: str = "unknown"
    indoor: bool = False
    private: bool = False
    occupant_count: int = 0
    item_count: int = 0
    exits: list[ClientExitView] = Field(default_factory=list)


class WorldOverviewResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    room_count: int = 0
    character_count: int = 0
    rooms: list[WorldOverviewRoomView] = Field(default_factory=list)


class MemoryCharacterView(BaseModel):
    character_id: str
    name: str
    private_collection: str
    shared_collections: list[str] = Field(default_factory=list)


class MemoryCharactersResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    characters: list[MemoryCharacterView] = Field(default_factory=list)


class MemoryDocumentView(BaseModel):
    id: str
    document: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryDocumentsResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    collection: str
    documents: list[MemoryDocumentView] = Field(default_factory=list)


class MemoryDocumentUpdateRequest(BaseModel):
    document: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryDocumentResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    collection: str
    document: MemoryDocumentView


class ActionSearchResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    query: str = ""
    mode: str = "substring"
    total_available: int = 0
    returned: int = 0
    actions: list[ClientActionView] = Field(default_factory=list)


class ExamineResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    id: str
    name: str
    kind: str = "other"
    is_character: bool = False
    is_self: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    status: list[str] = Field(default_factory=list)
    points: ClientPointsView | None = None


class ClientChecklistItemView(BaseModel):
    id: str
    text: str
    completed: bool = False


class CharacterProjectionResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    character_id: str
    character_name: str
    can_perceive: bool
    portrait: ClientImageView = Field(default_factory=ClientImageView)
    room: ClientRoomView = Field(default_factory=ClientRoomView)
    inventory: list[ClientTargetView] = Field(default_factory=list)
    points: ClientPointsView = Field(default_factory=ClientPointsView)
    controller: ClientControllerView | None = None
    sheet: ClientCharacterSheetView = Field(default_factory=ClientCharacterSheetView)
    current_goal: str = ""
    suggested_actions: list[str] = Field(default_factory=list)
    checklist: list[ClientChecklistItemView] = Field(default_factory=list)
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


class WebControllerFallbackRequest(BaseModel):
    character_id: str
    client_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_LENGTH)
    claim_id: str | None = None
    fallback_controller: str | None = None
    fallback_reason: str | None = None
    llm_profile_name: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    timeout_seconds: int | None = Field(
        default=None, ge=CLAIM_TIMEOUT_MIN_SECONDS, le=CLAIM_TIMEOUT_MAX_SECONDS
    )


class WebControllerClaimRequest(WebControllerFallbackRequest):
    label: str = Field(default="web", max_length=IDENTIFIER_MAX_LENGTH)


class WebControllerFallbackResponse(BaseModel):
    ok: bool = True
    character_id: str
    controller_id: str
    controller_generation: int
    claim_id: str
    claim_secret: str
    fallback_controller: str
    timeout_seconds: int


class WebControllerClaimResponse(WebControllerFallbackResponse):
    pass


class ClaimReleaseResponse(BaseModel):
    ok: bool = True
    character_id: str
    controller_id: str
    claim_id: str
    released: bool = True


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


class WorldImageGenerationRequest(BaseModel):
    entity_id: str
    purpose: str = "portrait"
    template: str = ""
    extra: str = ""
    alpha: bool = False
    force: bool = False


class EventImageRequest(BaseModel):
    extra: str = ""


class WorldImageGenerationResponse(BaseModel):
    ok: bool = True
    schema_version: int = 1
    world_epoch: int
    job_id: str
    status: str
    entity_id: str
    purpose: str
    url: str = ""
    alpha_url: str = ""
    error: str | None = None


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
    generated_at_unix: float | None = None
    next_tick_at_unix: float | None = None
    tick_seconds: float | None = None
    time_scale: float | None = None
    game_seconds_per_tick: float | None = None


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


class StoredControllerDefinitions(BaseModel):
    """Editor-loaded controller definitions persisted to the definition store."""

    scripts: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)


class ControllerDefinitionListResponse(BaseModel):
    """All registered controller definitions plus the authorable leaf library."""

    ok: bool = True
    scripts: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    condition_library: list[str] = Field(default_factory=list)
    action_library: list[str] = Field(default_factory=list)
    stored: StoredControllerDefinitions = Field(default_factory=StoredControllerDefinitions)


__all__ = [
    "ControllerDefinitionListResponse",
    "StoredControllerDefinitions",
    "CommandCostRequest",
    "CommandCancelResponse",
    "CommandRequest",
    "CommandResponse",
    "ControllerAssignmentRequest",
    "ClientActionArgumentView",
    "ClientActionView",
    "ClientCharacterSheetView",
    "ClientChecklistItemView",
    "CharacterImageUploadResponse",
    "CharacterProjectionResponse",
    "CharacterQueuedCommandsResponse",
    "ClientControllerView",
    "ClientEntityView",
    "ClientExitView",
    "ClientImageView",
    "ClientPointsView",
    "ClientRoomView",
    "ClientSheetEntryView",
    "ClientSheetMetricView",
    "ClientSpriteBoundsView",
    "ClientSpritePositionView",
    "ClientSpriteView",
    "ClientTargetView",
    "DmProjectionResponse",
    "DmRoomProjectionView",
    "EventImageRequest",
    "FeatureStatusResponse",
    "QueuedCommandView",
    "RecentEventsResponse",
    "RoomProjectionEntityView",
    "RoomProjectionResponse",
    "RoomProjectionRoomView",
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
    "WorldImageGenerationRequest",
    "WorldImageGenerationResponse",
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
