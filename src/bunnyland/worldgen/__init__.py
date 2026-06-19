"""World generation (spec 22): LLM proposes, the engine validates and instantiates.

Two paths coexist: the one-shot ``WorldProposal``/``instantiate`` flow, and the
breadth-first ``RecursiveWorldGenerator`` that grows the room graph node-by-node.
"""

from ..core.components import GenerationIntentComponent
from .builder import StubWorldBuilder, WorldBuilder
from .defaults import DEFAULT_WORLDGEN_MODEL
from .generators import (
    GenOptions,
    WorldGenerator,
    collect_generators,
    empty_generator,
    halloween_generator,
    holiday_generator,
    oneshot_generator,
    recursive_generator,
    tower_debate_generator,
    traced_generate,
    waiting_room_generator,
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
    StoryEventProposal,
    WorldProposal,
)
from .recursive import RecursiveWorldGenerator
from .recursive_builder import (
    OllamaRecursiveBuilder,
    OllamaWorldAgent,
    OpenRouterWorldAgent,
    RecursiveWorldBuilder,
    StubRecursiveBuilder,
    StubWorldAgent,
    WorldAgent,
)

__all__ = [
    "CharacterProposal",
    "CharacterSpec",
    "DEFAULT_WORLDGEN_MODEL",
    "DanglingResolution",
    "DoorProposal",
    "ExitSpec",
    "GenOptions",
    "GenerationIntentComponent",
    "InstantiatedWorld",
    "ItemProposal",
    "ObjectSpec",
    "OllamaRecursiveBuilder",
    "OllamaWorldAgent",
    "OpenRouterWorldAgent",
    "RecursiveWorldBuilder",
    "RecursiveWorldGenerator",
    "RoomContentsProposal",
    "RoomNodeProposal",
    "RoomSpec",
    "StoryEventProposal",
    "StubRecursiveBuilder",
    "StubWorldAgent",
    "StubWorldBuilder",
    "WorldAgent",
    "WorldBuilder",
    "WorldGenerator",
    "WorldProposal",
    "collect_generators",
    "empty_generator",
    "halloween_generator",
    "holiday_generator",
    "instantiate",
    "oneshot_generator",
    "recursive_generator",
    "tower_debate_generator",
    "traced_generate",
    "validate_proposal",
    "waiting_room_generator",
]
