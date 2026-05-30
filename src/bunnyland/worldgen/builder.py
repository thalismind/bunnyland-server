"""World builders (spec 22.1). A builder proposes structured content from a seed.

``StubWorldBuilder`` is deterministic and dependency-free; it produces a small marsh
world that exercises the MVP checklist (spec 28.2). The Ollama-backed builder lives in
``ollama_builder`` and returns the same proposal type.
"""

from __future__ import annotations

from typing import Protocol

from .proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal


class WorldBuilder(Protocol):
    def propose(self, seed: str) -> WorldProposal: ...


class StubWorldBuilder:
    """A fixed, deterministic proposal used for tests and offline development."""

    system_prompt = ""  # deterministic; no LLM prompt

    def propose(self, seed: str) -> WorldProposal:
        return WorldProposal(
            seed=seed,
            rooms=[
                RoomSpec(
                    key="burrow",
                    title="Mosslit Burrow",
                    biome="marsh",
                    indoor=True,
                    light=0.3,
                    celsius=18.0,
                ),
                RoomSpec(
                    key="tunnel",
                    title="North Tunnel",
                    biome="marsh",
                    indoor=True,
                    light=0.6,
                    celsius=14.0,
                ),
            ],
            exits=[
                ExitSpec(from_key="burrow", direction="north", to_key="tunnel"),
                ExitSpec(from_key="tunnel", direction="south", to_key="burrow"),
            ],
            objects=[
                ObjectSpec(
                    key="berries",
                    room_key="burrow",
                    name="three berries",
                    kind="food",
                    nutrition=5.0,
                    satiety=20.0,
                ),
                ObjectSpec(
                    key="basin",
                    room_key="burrow",
                    name="a stone basin of water",
                    kind="water",
                    portable=False,
                    hydration=25.0,
                    renewable=True,
                ),
                ObjectSpec(
                    key="chest",
                    room_key="burrow",
                    name="an oak chest",
                    kind="container",
                    portable=False,
                    open=False,
                ),
                ObjectSpec(
                    key="paper",
                    room_key="burrow",
                    name="a scrap of paper",
                    kind="paper",
                    writable=True,
                ),
            ],
            characters=[
                CharacterSpec(
                    key="juniper",
                    name="Juniper",
                    room_key="burrow",
                    controller="suspended",  # claimable by a human
                    traits=("cautious", "kind"),
                ),
                CharacterSpec(
                    key="hazel",
                    name="Hazel",
                    room_key="burrow",
                    controller="llm",
                    llm_profile="elder",
                    llm_model="llama3",
                    traits=("curious", "talkative"),
                    goals=("learn the marsh's secrets",),
                ),
            ],
        )


__all__ = ["StubWorldBuilder", "WorldBuilder"]
