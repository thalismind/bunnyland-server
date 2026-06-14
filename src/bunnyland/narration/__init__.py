"""Read-side narration assembled from visible ECS state and domain events."""

from .projection import (
    NarrationIssue,
    NarrationProjection,
    SceneCluster,
    SceneEvent,
    SceneFact,
    SceneInput,
    SceneNarration,
    check_grounding,
    render_scene,
)

__all__ = [
    "NarrationIssue",
    "NarrationProjection",
    "SceneCluster",
    "SceneEvent",
    "SceneFact",
    "SceneInput",
    "SceneNarration",
    "check_grounding",
    "render_scene",
]
