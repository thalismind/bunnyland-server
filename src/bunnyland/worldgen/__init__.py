"""World generation (spec 22): LLM proposes, the engine validates and instantiates.

Two paths coexist: the one-shot ``WorldProposal``/``instantiate`` flow, and the
breadth-first ``RecursiveWorldGenerator`` that grows the room graph node-by-node.
"""

from .builder import StubWorldBuilder, WorldBuilder
from .instantiate import InstantiatedWorld, instantiate, validate_proposal
from .proposal import (
    CharacterProposal,
    CharacterSpec,
    DanglingResolution,
    DoorProposal,
    ExitSpec,
    ItemProposal,
    ObjectSpec,
    RoomContentsProposal,
    RoomNodeProposal,
    RoomSpec,
    WorldProposal,
)
from .recursive import RecursiveWorldGenerator
from .recursive_builder import (
    OllamaRecursiveBuilder,
    RecursiveWorldBuilder,
    StubRecursiveBuilder,
)

__all__ = [
    "CharacterProposal",
    "CharacterSpec",
    "DanglingResolution",
    "DoorProposal",
    "ExitSpec",
    "InstantiatedWorld",
    "ItemProposal",
    "ObjectSpec",
    "OllamaRecursiveBuilder",
    "RecursiveWorldBuilder",
    "RecursiveWorldGenerator",
    "RoomContentsProposal",
    "RoomNodeProposal",
    "RoomSpec",
    "StubRecursiveBuilder",
    "StubWorldBuilder",
    "WorldBuilder",
    "WorldProposal",
    "instantiate",
    "validate_proposal",
]
