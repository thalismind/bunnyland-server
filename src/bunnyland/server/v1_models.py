"""Formal v1 transport models.

These models deliberately describe resources at the HTTP boundary.  Domain commands and
the preview API models remain internal implementation details while first-party clients
migrate to this contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..content import ContentLibrary
from ..core.commands import Lane, OnInsufficientPoints
from ..core.events import EventVisibility
from ..core.perspective import PerspectiveQueryRequest
from .models import (
    CharacterChatActionResult,
    CharacterChatHistoryMessage,
    ClientActionView,
    ClientCharacterSheetView,
    ClientChecklistItemView,
    ClientControllerView,
    ClientImageView,
    ClientPointsView,
    ClientRoomView,
    ClientTargetView,
    CommandCostRequest,
    EcsTypeSchema,
    FeatureStatusResponse,
    KnownRoomView,
    MemoryDocumentUpdateRequest,
    QueuedCommandView,
    RoomProjectionRoomView,
    StoredControllerDefinitions,
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldGenerateRequest,
    WorldGeneratorInfo,
    WorldImageGenerationRequest,
    WorldItemGenerationRequest,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
    WorldSaveResponse,
)


class ProblemDetails(BaseModel):
    """RFC 9457 problem details with Bunnyland's stable machine-readable code."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str = ""
    instance: str | None = None
    code: str


class WorldResource(BaseModel):
    world_id: str
    world_epoch: int


class PublicWorldResource(WorldResource):
    title: str
    description: str
    content_flags: list[str]


class V1Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterResource(BaseModel):
    id: str
    name: str
    kind: str = "character"
    suspended: bool = False


class CharacterCollection(WorldResource):
    characters: list[CharacterResource] = Field(default_factory=list)


class CharacterProfileResource(WorldResource):
    projection_version: int = 1
    character_id: str
    character_name: str
    portrait: ClientImageView = Field(default_factory=ClientImageView)
    room: ClientRoomView = Field(default_factory=ClientRoomView)
    points: ClientPointsView = Field(default_factory=ClientPointsView)
    controller: ClientControllerView | None = None
    sheet: ClientCharacterSheetView = Field(default_factory=ClientCharacterSheetView)


class CatalogResource(WorldResource):
    components: dict[str, EcsTypeSchema] = Field(default_factory=dict)
    edges: dict[str, EcsTypeSchema] = Field(default_factory=dict)
    content: ContentLibrary
    queries: list[str] = Field(default_factory=list)
    capabilities: FeatureStatusResponse = Field(default_factory=FeatureStatusResponse)


class ClaimCreateRequest(V1Request):
    character_id: str
    label: str = Field(default="web", max_length=128)
    fallback_controller: str | None = None
    fallback_reason: str | None = None
    llm_profile_name: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    timeout_seconds: int | None = None


class ClaimFallbackUpdate(V1Request):
    kind: Literal["fallback"]
    fallback_controller: str | None = None
    fallback_reason: str | None = None
    llm_profile_name: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    timeout_seconds: int | None = None


class ClaimControlUpdate(V1Request):
    kind: Literal["control"]
    desired: Literal["active", "fallback"]


ClaimUpdateRequest = Annotated[
    ClaimFallbackUpdate | ClaimControlUpdate,
    Field(discriminator="kind"),
]


class ClaimResource(WorldResource):
    id: str
    character_id: str
    client_id: str
    controller_id: str
    controller_generation: int
    control: Literal["active", "fallback"]
    fallback_controller: str
    timeout_seconds: int


class ClaimCharacterResource(BaseModel):
    world_epoch: int
    character_id: str
    character_name: str
    can_perceive: bool
    portrait: ClientImageView = Field(default_factory=ClientImageView)
    room: ClientRoomView = Field(default_factory=ClientRoomView)
    inventory: list[ClientTargetView] = Field(default_factory=list)
    points: ClientPointsView = Field(default_factory=ClientPointsView)
    controller: ClientControllerView | None = None
    current_goal: str = ""
    suggested_actions: list[str] = Field(default_factory=list)
    checklist: list[ClientChecklistItemView] = Field(default_factory=list)
    known_rooms: list[KnownRoomView] = Field(default_factory=list)
    target_groups: dict[str, list[ClientTargetView]] = Field(default_factory=dict)


class ClaimSceneResource(BaseModel):
    world_epoch: int
    room: RoomProjectionRoomView


class ClaimProjectionResource(WorldResource):
    projection_version: int = 1
    claim: ClaimResource
    character: ClaimCharacterResource
    scene: ClaimSceneResource | None = None
    commands: list[QueuedCommandView] = Field(default_factory=list)
    sheet: ClientCharacterSheetView = Field(default_factory=ClientCharacterSheetView)
    actions: list[ClientActionView] = Field(default_factory=list)


class ClaimCommandRequest(V1Request):
    command_type: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    cost: CommandCostRequest = Field(default_factory=CommandCostRequest)
    lane: Lane = Lane.WORLD
    on_insufficient_points: OnInsufficientPoints = OnInsufficientPoints.QUEUE
    expires_at_epoch: int | None = None
    expected_epoch: int | None = None
    id: str | None = None


class CommandResource(WorldResource):
    id: str
    status: Literal["queued", "rejected", "cancelled"]
    reason: str = ""


class DomainEventResource(BaseModel):
    """Stable event header plus explicitly plugin-owned event data."""

    model_config = ConfigDict(extra="allow")

    event_id: str
    world_epoch: int
    created_at: datetime
    visibility: EventVisibility = EventVisibility.SYSTEM
    actor_id: str | None = None
    room_id: str | None = None
    target_ids: tuple[str, ...] = ()
    causation_id: str | None = None
    correlation_id: str | None = None


class EventDataResource(BaseModel):
    event_type: str
    event_key: str
    event: DomainEventResource


class EventFrameResource(BaseModel):
    type: Literal["event"]
    data: EventDataResource


class InvalidationDataResource(BaseModel):
    world_epoch: int


class InvalidationFrameResource(BaseModel):
    type: Literal["invalidate"]
    data: InvalidationDataResource


EventUpdateResource = Annotated[
    EventFrameResource | InvalidationFrameResource,
    Field(discriminator="type"),
]


class EventCollection(WorldResource):
    events: list[EventUpdateResource] = Field(default_factory=list)
    complete: bool = True
    available_after_epoch: int | None = None


class ChatJobRequest(V1Request):
    kind: Literal["chat"]
    message: str = Field(min_length=1, max_length=4000)
    history_summary: str = Field(default="", max_length=12000)
    history: list[CharacterChatHistoryMessage] = Field(default_factory=list, max_length=24)


class CharacterChatReplyRequest(V1Request):
    reply: str = Field(min_length=1, max_length=4000)


class SceneImageJobRequest(V1Request):
    kind: Literal["scene_image"]


class ChatJobResult(V1Request):
    world_epoch: int
    character_id: str
    reply: str = ""
    command_id: str | None = None
    complete: bool | None = None
    action: CharacterChatActionResult = Field(default_factory=CharacterChatActionResult)


class ImageJobResult(V1Request):
    world_epoch: int
    job_id: str
    status: str
    entity_id: str
    purpose: str
    generator: str = "comfyui"
    url: str = ""
    alpha_url: str = ""
    error: str | None = None


class WorldGenerationJobResult(V1Request):
    job_id: str | None = None
    status: str
    seed: str | None = None
    generator: str | None = None
    world_epoch: int
    rooms: int | None = None
    characters: int | None = None
    error: str | None = None
    saved: WorldSaveResponse | None = None


class RoomGenerationJobResult(V1Request):
    source_room_id: str
    door_entity_id: str
    generated_title: str
    patch: WorldPatchRequest


class CharacterGenerationJobResult(V1Request):
    room_entity_id: str
    generated_name: str
    patch: WorldPatchRequest


class ItemGenerationJobResult(V1Request):
    container_entity_id: str
    generated_name: str
    patch: WorldPatchRequest


class EventGenerationJobResult(V1Request):
    room_entity_id: str
    generated_title: str
    generated_kind: str
    patch: WorldPatchRequest


JobResult = (
    ChatJobResult
    | ImageJobResult
    | WorldGenerationJobResult
    | RoomGenerationJobResult
    | CharacterGenerationJobResult
    | ItemGenerationJobResult
    | EventGenerationJobResult
)


class JobResource(WorldResource):
    id: str
    kind: Literal["chat", "scene_image", "world", "room", "character", "item", "event", "image"]
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    result: JobResult | None = None
    failure: ProblemDetails | None = None


class ClaimQueryRequest(PerspectiveQueryRequest):
    model_config = ConfigDict(extra="forbid")


class RuntimePatchRequest(V1Request):
    paused: bool


class CheckpointRequest(V1Request):
    reason: str = "requested through v1"


class ControllerAssignment(V1Request):
    controller_id: str


class ControllerDefinitionRequest(V1Request):
    definition: dict[str, JsonValue]


class ControllerDefinitionsResource(WorldResource):
    scripts: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    condition_library: list[str] = Field(default_factory=list)
    action_library: list[str] = Field(default_factory=list)
    stored: StoredControllerDefinitions = Field(default_factory=StoredControllerDefinitions)


class GeneratorCollection(WorldResource):
    generators: list[WorldGeneratorInfo] = Field(default_factory=list)


class GenerateWorldRequest(WorldGenerateRequest):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["world"] = "world"


class GenerateRoomRequest(WorldRoomGenerationRequest):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["room"] = "room"


class GenerateCharacterRequest(WorldCharacterGenerationRequest):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["character"] = "character"


class GenerateItemRequest(WorldItemGenerationRequest):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["item"] = "item"


class GenerateEventRequest(WorldEventGenerationRequest):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["event"] = "event"


class GenerateImageRequest(WorldImageGenerationRequest):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["image"] = "image"


GenerationJobRequest = Annotated[
    GenerateWorldRequest
    | GenerateRoomRequest
    | GenerateCharacterRequest
    | GenerateItemRequest
    | GenerateEventRequest
    | GenerateImageRequest,
    Field(discriminator="kind"),
]


__all__ = [
    "CatalogResource",
    "CharacterGenerationJobResult",
    "CharacterCollection",
    "CharacterResource",
    "CharacterChatReplyRequest",
    "CharacterProfileResource",
    "ChatJobRequest",
    "ChatJobResult",
    "CheckpointRequest",
    "ClaimCharacterResource",
    "ClaimCommandRequest",
    "ClaimCreateRequest",
    "ClaimProjectionResource",
    "ClaimQueryRequest",
    "ClaimResource",
    "ClaimSceneResource",
    "ClaimUpdateRequest",
    "CommandResource",
    "ControllerAssignment",
    "ControllerDefinitionRequest",
    "ControllerDefinitionsResource",
    "DomainEventResource",
    "EventCollection",
    "EventDataResource",
    "EventFrameResource",
    "EventGenerationJobResult",
    "EventUpdateResource",
    "GenerateCharacterRequest",
    "GenerateEventRequest",
    "GenerateImageRequest",
    "GenerateItemRequest",
    "GenerateRoomRequest",
    "GenerateWorldRequest",
    "GeneratorCollection",
    "GenerationJobRequest",
    "ImageJobResult",
    "InvalidationDataResource",
    "InvalidationFrameResource",
    "ItemGenerationJobResult",
    "JobResource",
    "JobResult",
    "MemoryDocumentUpdateRequest",
    "PerspectiveQueryRequest",
    "ProblemDetails",
    "RoomGenerationJobResult",
    "RuntimePatchRequest",
    "SceneImageJobRequest",
    "V1Request",
    "WorldGenerationJobResult",
    "PublicWorldResource",
    "WorldPatchRequest",
    "WorldResource",
]
