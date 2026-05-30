"""Ollama Cloud world builder (spec 22). Optional: requires the ``llm`` extra.

Asks an Ollama model for a JSON world proposal and validates it against the
``WorldProposal`` schema. The model output is untrusted: it is parsed and validated, and
only the validated proposal is ever instantiated (the LLM never touches the ECS).
"""

from __future__ import annotations

import json

from .proposal import WorldProposal

_SYSTEM_PROMPT = """You are the world-builder for an asynchronous social sandbox.
From the seed, return ONLY JSON matching this shape (no prose):
{
  "seed": str,
  "rooms": [{"key","title","biome","indoor",bool,"light":0..1,"celsius":num}],
  "exits": [{"from_key","direction","to_key","locked":bool}],
  "objects": [{"key","room_key","name","kind":"item|food|water|container|paper|key|door",
               "portable":bool,"nutrition","satiety","hydration","renewable","open",
               "writable","key_name","locked"}],
  "characters": [{"key","name","room_key","species","controller":"llm|suspended"}]
}
Make a small, connected world with at least two rooms, food, water, a container,
a writable object, one llm character, and one suspended (claimable) character."""


class OllamaWorldBuilder:
    """Generates a proposal via Ollama Cloud. ``ollama`` is imported lazily."""

    #: The literal DM system prompt this builder sends, recorded in saved worlds.
    system_prompt = _SYSTEM_PROMPT

    def __init__(
        self,
        *,
        model: str = "deepseek-v4-flash",
        host: str | None = None,
        api_key: str | None = None,
    ):
        try:
            import ollama
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "OllamaWorldBuilder requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = ollama.Client(host=host, headers=headers) if host else ollama.Client()
        self._model = model

    def propose(self, seed: str) -> WorldProposal:  # pragma: no cover - needs network + extra
        response = self._client.chat(
            model=self._model,
            format="json",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Seed: {seed}"},
            ],
        )
        content = response["message"]["content"]
        data = json.loads(content)
        data.setdefault("seed", seed)
        return WorldProposal.model_validate(data)


__all__ = ["OllamaWorldBuilder"]
