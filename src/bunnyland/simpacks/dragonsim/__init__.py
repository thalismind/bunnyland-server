"""Dragon simulation plugin and shared quest lifecycle."""

from .effects import EffectModifier, EffectResolution, EffectSpec, effect_spec, resolve_effect
from .events import QuestAcceptedEvent, QuestCompletedEvent

__all__ = [
    "EffectModifier",
    "EffectResolution",
    "EffectSpec",
    "QuestAcceptedEvent",
    "QuestCompletedEvent",
    "effect_spec",
    "resolve_effect",
]
