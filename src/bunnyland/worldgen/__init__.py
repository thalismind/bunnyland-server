"""World generation (spec 22): LLM proposes, the engine validates and instantiates.

Two paths coexist: the one-shot ``WorldProposal``/``instantiate`` flow, and the
breadth-first ``RecursiveWorldGenerator`` that grows the room graph node-by-node.
"""

from .builder import StubWorldBuilder, WorldBuilder
from .defaults import DEFAULT_WORLDGEN_MODEL
from .generators import (
    GenOptions,
    WorldGenerator,
    collect_generators,
    oneshot_generator,
    recursive_generator,
)
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
    "DEFAULT_WORLDGEN_MODEL",
    "DanglingResolution",
    "DoorProposal",
    "ExitSpec",
    "GenOptions",
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
    "WorldGenerator",
    "WorldProposal",
    "collect_generators",
    "instantiate",
    "oneshot_generator",
    "recursive_generator",
    "validate_proposal",
]
