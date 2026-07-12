"""Prompt generation (spec 16): one foundation for humans and LLMs.

The builder assembles a structured ``PromptContext`` from ECS state and projections, then
renders it to text. Mechanics own their own fragments (needs, etc.) and are injected as
fragment providers, so the builder holds no domain-specific phrasing of its own.
"""

from .builder import PromptBuilder, PromptContext, render_prompt
from .context import (
    ComponentPromptContext,
    PerspectiveName,
    PerspectivePhrase,
    PromptAccess,
    PromptPerspective,
)
from .facts import (
    DETAILED_DETAIL_CUTOFF,
    STANDARD_DETAIL_CUTOFF,
    PromptFact,
    PromptFactLike,
)

__all__ = [
    "ComponentPromptContext",
    "DETAILED_DETAIL_CUTOFF",
    "PromptFact",
    "PromptFactLike",
    "PerspectiveName",
    "PerspectivePhrase",
    "PromptAccess",
    "PromptBuilder",
    "PromptContext",
    "PromptPerspective",
    "STANDARD_DETAIL_CUTOFF",
    "render_prompt",
]
