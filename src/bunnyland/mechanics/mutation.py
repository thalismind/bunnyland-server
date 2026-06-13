"""Shared source-specific mutation and radiation protection state."""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component

from ..prompts import ComponentPromptContext


@dataclass(frozen=True)
class RadiationShieldComponent(Component):
    strength: float = 100.0


@dataclass(frozen=True)
class ChaosMutationPressureComponent(Component):
    """Chaos-specific mutation pressure from warp/corruption exposure."""

    amount: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or self.amount <= 0.0:
            return ()
        return (f"Chaos mutation pressure: {self.amount:g}.",)


@dataclass(frozen=True)
class RadiationMutationPressureComponent(Component):
    """Radiation-specific mutation pressure from fallout, reactors, and hot zones."""

    amount: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or self.amount <= 0.0:
            return ()
        return (f"Radiation mutation pressure: {self.amount:g}.",)


@dataclass(frozen=True)
class CyberneticMutationPressureComponent(Component):
    """Cybernetic/body-mod pressure reserved for augmentation systems."""

    amount: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or self.amount <= 0.0:
            return ()
        return (f"Cybernetic mutation pressure: {self.amount:g}.",)


__all__ = [
    "ChaosMutationPressureComponent",
    "CyberneticMutationPressureComponent",
    "RadiationMutationPressureComponent",
    "RadiationShieldComponent",
]
