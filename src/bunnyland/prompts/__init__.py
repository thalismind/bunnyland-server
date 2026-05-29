"""Prompt generation (spec 16): one foundation for humans and LLMs.

The builder assembles a structured ``PromptContext`` from ECS state and projections, then
renders it to text. Mechanics own their own fragments (needs, etc.) and are injected as
fragment providers, so the builder holds no domain-specific phrasing of its own.
"""

from .builder import PromptBuilder, PromptContext, render_prompt

__all__ = ["PromptBuilder", "PromptContext", "render_prompt"]
