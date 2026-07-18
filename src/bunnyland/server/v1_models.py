"""Formal v1 transport models.

These models deliberately describe resources at the HTTP boundary.  Domain commands and
the preview API models remain internal implementation details while first-party clients
migrate to this contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.commands import Lane, OnInsufficientPoints
from ..core.perspective import PerspectiveQueryRequest
from .models import (
    CharacterChatHistoryMessage,
    ClientActionView,
    CommandCostRequest,
    MemoryDocumentUpdateRequest,
    WorldCharacterGenerationRequest,
    WorldEventGenerationRequest,
    WorldGenerateRequest,
    WorldImageGenerationRequest,
    WorldItemGenerationRequest,
    WorldPatchRequest,
    WorldRoomGenerationRequest,
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


class V1Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterResource(BaseModel):
    id: str
    name: str
    kind: str = "character"
    suspended: bool = False


class CharacterCollection(WorldResource):
    characters: list[CharacterResource] = Field(default_factory=list)


class CatalogResource(WorldResource):
    components: dict[str, Any] = Field(default_factory=dict)
    edges: dict[str, Any] = Field(default_factory=dict)
    content: dict[str, Any] = Field(default_factory=dict)
    queries: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)


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


class ClaimProjectionResource(WorldResource):
    projection_version: int = 1
    claim: ClaimResource
    character: dict[str, Any]
    scene: dict[str, Any]
    commands: list[dict[str, Any]] = Field(default_factory=list)
    sheet: dict[str, Any] = Field(default_factory=dict)
    actions: list[ClientActionView] = Field(default_factory=list)


class ClaimCommandRequest(V1Request):
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
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


class EventCollection(WorldResource):
    events: list[dict[str, Any]] = Field(default_factory=list)
    complete: bool = True
    available_after_epoch: int | None = None


class ChatJobRequest(V1Request):
    kind: Literal["chat"]
    message: str = Field(min_length=1, max_length=4000)
    history_summary: str = Field(default="", max_length=12000)
    history: list[CharacterChatHistoryMessage] = Field(default_factory=list, max_length=24)


class SceneImageJobRequest(V1Request):
    kind: Literal["scene_image"]


PlayerJobRequest = Annotated[ChatJobRequest | SceneImageJobRequest, Field(discriminator="kind")]


class JobResource(WorldResource):
    id: str
    kind: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    result: dict[str, Any] | None = None
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
    definition: dict[str, Any]


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
    "CharacterCollection",
    "CheckpointRequest",
    "ClaimCommandRequest",
    "ClaimCreateRequest",
    "ClaimProjectionResource",
    "ClaimQueryRequest",
    "ClaimResource",
    "ClaimUpdateRequest",
    "CommandResource",
    "ControllerAssignment",
    "ControllerDefinitionRequest",
    "EventCollection",
    "GenerationJobRequest",
    "JobResource",
    "MemoryDocumentUpdateRequest",
    "PerspectiveQueryRequest",
    "PlayerJobRequest",
    "ProblemDetails",
    "RuntimePatchRequest",
    "WorldPatchRequest",
]
