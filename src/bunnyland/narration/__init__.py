"""Read-side narration assembled from visible ECS state and domain events."""

from .projection import (
    DEFAULT_VOICE,
    DEFAULT_VOICE_REGISTRY,
    NarrationIssue,
    NarrationProjection,
    NarrationVoice,
    NarrationVoiceRegistry,
    SceneCluster,
    SceneEvent,
    SceneFact,
    SceneInput,
    SceneNarration,
    check_grounding,
    render_scene,
)

__all__ = [
    "DEFAULT_VOICE",
    "DEFAULT_VOICE_REGISTRY",
    "NarrationIssue",
    "NarrationProjection",
    "NarrationVoice",
    "NarrationVoiceRegistry",
    "SceneCluster",
    "SceneEvent",
    "SceneFact",
    "SceneInput",
    "SceneNarration",
    "check_grounding",
    "render_scene",
]
