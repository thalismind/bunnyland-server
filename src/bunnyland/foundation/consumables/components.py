"""Consumable item components (spec 11.7).

Hunger and thirst are separate mechanics fed by separate components. A single item may
carry several (a bowl of soup is food and drink and consumable).
"""

from __future__ import annotations

from pydantic.dataclasses import dataclass
from relics import Component


@dataclass(frozen=True)
class ConsumableComponent(Component):
    current_uses: int = 1
    max_uses: int = 1


@dataclass(frozen=True)
class FoodComponent(Component):
    nutrition: float
    satiety: float
    raw: bool = False
    spoiled: bool = False


@dataclass(frozen=True)
class DrinkableComponent(Component):
    hydration: float
    purity: float = 1.0


__all__ = ["ConsumableComponent", "DrinkableComponent", "FoodComponent"]
