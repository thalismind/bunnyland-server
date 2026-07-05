"""Shared CLI/config defaults."""

from __future__ import annotations

from .llm_agents import DEFAULT_MODEL as DEFAULT_CHARACTER_MODEL
from .worldgen import DEFAULT_WORLDGEN_MODEL

OLLAMA_CLOUD_HOST = "https://ollama.com"

__all__ = ["DEFAULT_CHARACTER_MODEL", "DEFAULT_WORLDGEN_MODEL", "OLLAMA_CLOUD_HOST"]
