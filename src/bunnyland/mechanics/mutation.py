"""Shared source-specific mutation and radiation protection state."""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component


@dataclass(frozen=True)
class RadiationShieldComponent(Component):
    strength: float = 100.0


@dataclass(frozen=True)
class ChaosMutationPressureComponent(Component):
    """Chaos-specific mutation pressure from warp/corruption exposure."""

    amount: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class RadiationMutationPressureComponent(Component):
    """Radiation-specific mutation pressure from fallout, reactors, and hot zones."""

    amount: float = 0.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class CyberneticMutationPressureComponent(Component):
    """Cybernetic/body-mod pressure reserved for augmentation systems."""

    amount: float = 0.0
    last_updated_epoch: int = 0


__all__ = [
    "ChaosMutationPressureComponent",
    "CyberneticMutationPressureComponent",
    "RadiationMutationPressureComponent",
    "RadiationShieldComponent",
]
