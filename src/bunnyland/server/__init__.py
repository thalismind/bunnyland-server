"""Optional server API helpers for web clients.

The dependency-free pieces in this package expose world snapshots and event streams. The
FastAPI app factory is imported lazily by callers that install web-server dependencies.
"""

from .models import (
    CommandRequest,
    CommandResponse,
    WebControllerClaimRequest,
    WebControllerClaimResponse,
    WebControllerFallbackRequest,
    WebControllerFallbackResponse,
    WorldCharacterGenerationRequest,
    WorldCharacterGenerationResponse,
    WorldGenerateRequest,
    WorldGenerateResponse,
    WorldGenerationStatusResponse,
    WorldGeneratorInfo,
    WorldGeneratorListResponse,
    WorldItemGenerationRequest,
    WorldItemGenerationResponse,
    WorldPatchRequest,
    WorldPatchResponse,
    WorldRoomGenerationRequest,
    WorldRoomGenerationResponse,
    WorldRuntimeResponse,
    WorldSaveResponse,
    WorldSchemaResponse,
)
from .serialization import event_message, serialize_event, serialize_world
from .subscriptions import EventStream, EventSubscription

__all__ = [
    "CommandRequest",
    "CommandResponse",
    "EventStream",
    "EventSubscription",
    "WebControllerFallbackRequest",
    "WebControllerFallbackResponse",
    "WebControllerClaimRequest",
    "WebControllerClaimResponse",
    "WorldCharacterGenerationRequest",
    "WorldCharacterGenerationResponse",
    "WorldGenerateRequest",
    "WorldGenerateResponse",
    "WorldGenerationStatusResponse",
    "WorldGeneratorInfo",
    "WorldGeneratorListResponse",
    "WorldItemGenerationRequest",
    "WorldItemGenerationResponse",
    "WorldPatchRequest",
    "WorldPatchResponse",
    "WorldRoomGenerationRequest",
    "WorldRoomGenerationResponse",
    "WorldRuntimeResponse",
    "WorldSaveResponse",
    "WorldSchemaResponse",
    "event_message",
    "serialize_event",
    "serialize_world",
]
