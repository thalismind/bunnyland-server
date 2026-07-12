"""Ollama Cloud world builder (spec 22). Optional: requires the ``llm`` extra.

Asks an Ollama model for a JSON world proposal and validates it against the
``WorldProposal`` schema. The model output is untrusted: it is parsed and validated, and
only the validated proposal is ever instantiated (the LLM never touches the ECS).
"""

from __future__ import annotations

import logging

from .defaults import DEFAULT_WORLDGEN_MODEL
from .proposal import WorldProposal

logger = logging.getLogger("bunnyland.worldgen")

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
        model: str = DEFAULT_WORLDGEN_MODEL,
        host: str | None = None,
        api_key: str | None = None,
    ):
        try:
            import ollama
        except ImportError as exc:
            raise RuntimeError(
                "OllamaWorldBuilder requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        client_cls = ollama.AsyncClient
        self._client = client_cls(host=host, headers=headers) if host else client_cls()
        self._model = model

    async def propose(self, seed: str) -> WorldProposal:
        response = await self._client.chat(
            model=self._model,
            format=WorldProposal.model_json_schema(),
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Seed: {seed}"},
            ],
        )
        content = response["message"]["content"]
        proposal = WorldProposal.model_validate_json(content)
        return repair_world_proposal(proposal.model_copy(update={"seed": seed}))


def repair_world_proposal(proposal: WorldProposal) -> WorldProposal:
    """Repair small LLM proposal reference mistakes before strict instantiation.

    The flat proposal schema does not support nested object contents yet. Live models
    sometimes put an item in a container key instead of a room key; keep the item playable
    by placing it in the first room. Dangling exits are dropped because inventing topology
    would be more surprising than omitting a bad edge.
    """

    if not proposal.rooms:
        return proposal
    room_keys = {room.key for room in proposal.rooms}
    default_room_key = proposal.rooms[0].key

    repaired_objects = []
    repaired_object_count = 0
    for obj in proposal.objects:
        if obj.room_key in room_keys:
            repaired_objects.append(obj)
            continue
        repaired_objects.append(obj.model_copy(update={"room_key": default_room_key}))
        repaired_object_count += 1

    repaired_characters = []
    repaired_character_count = 0
    for character in proposal.characters:
        if character.room_key in room_keys:
            repaired_characters.append(character)
            continue
        repaired_characters.append(character.model_copy(update={"room_key": default_room_key}))
        repaired_character_count += 1

    repaired_exits = [
        exit_
        for exit_ in proposal.exits
        if exit_.from_key in room_keys and exit_.to_key in room_keys
    ]
    dropped_exit_count = len(proposal.exits) - len(repaired_exits)
    if repaired_object_count or repaired_character_count or dropped_exit_count:
        logger.warning(
            "repaired live world proposal references: %s object(s), %s character(s), "
            "%s dropped exit(s)",
            repaired_object_count,
            repaired_character_count,
            dropped_exit_count,
        )
    return proposal.model_copy(
        update={
            "objects": repaired_objects,
            "characters": repaired_characters,
            "exits": repaired_exits,
        }
    )


__all__ = ["OllamaWorldBuilder", "repair_world_proposal"]
