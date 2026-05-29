"""World generation (spec 22): LLM proposes, the engine validates and instantiates."""

from .builder import StubWorldBuilder, WorldBuilder
from .instantiate import InstantiatedWorld, instantiate, validate_proposal
from .proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal

__all__ = [
    "CharacterSpec",
    "ExitSpec",
    "InstantiatedWorld",
    "ObjectSpec",
    "RoomSpec",
    "StubWorldBuilder",
    "WorldBuilder",
    "WorldProposal",
    "instantiate",
    "validate_proposal",
]
