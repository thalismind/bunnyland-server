"""Hunger and thirst: separate components, systems, and events (spec 9.4, 11.11, 23.3).

Hunger and thirst are deliberately distinct mechanics. Each rises over real time and is
relieved by a different action (eat vs drink). Both reuse the shared ``Meter`` primitive
but never share a component or system.

These systems are *harmful* world-participation systems, so they exclude suspended and
dead characters via their own queries (spec 8.1, 23.3).
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Frequency, System

from ..core.components import DeadComponent, SuspendedComponent
from ..core.ecs import replace_component
from ..core.events import DomainEvent
from .meter import Meter, band, changed

SECONDS_PER_HOUR = 3600.0


# --------------------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HungerComponent(Component):
    meter: Meter = Meter()
    metabolism: float = 1.0  # hunger points gained per game hour
    last_ate_epoch: int | None = None


@dataclass(frozen=True)
class ThirstComponent(Component):
    meter: Meter = Meter()
    hydration_loss_rate: float = 1.5  # thirst points gained per game hour
    last_drank_epoch: int | None = None


# --------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------


class HungerChangedEvent(DomainEvent):
    value: float
    band: str


class ThirstChangedEvent(DomainEvent):
    value: float
    band: str


class FoodEatenEvent(DomainEvent):
    item_id: str
    satiety: float


class DrinkConsumedEvent(DomainEvent):
    source_id: str
    hydration: float


# --------------------------------------------------------------------------------------
# Systems
# --------------------------------------------------------------------------------------


class HungerSystem(System):
    """Raise hunger over time for active characters."""

    def query(self):
        return self.q.with_all([HungerComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        hours = delta / SECONDS_PER_HOUR
        for entity in entities:
            hunger = entity.get_component(HungerComponent)
            new_meter = changed(hunger.meter, hunger.metabolism * hours)
            if new_meter.value != hunger.meter.value:
                replace_component(entity, replace(hunger, meter=new_meter))


class ThirstSystem(System):
    """Raise thirst over time for active characters."""

    def query(self):
        return self.q.with_all([ThirstComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        hours = delta / SECONDS_PER_HOUR
        for entity in entities:
            thirst = entity.get_component(ThirstComponent)
            new_meter = changed(thirst.meter, thirst.hydration_loss_rate * hours)
            if new_meter.value != thirst.meter.value:
                replace_component(entity, replace(thirst, meter=new_meter))


def hunger_band(entity) -> str:
    return band(entity.get_component(HungerComponent).meter)


def thirst_band(entity) -> str:
    return band(entity.get_component(ThirstComponent).meter)


__all__ = [
    "DrinkConsumedEvent",
    "FoodEatenEvent",
    "HungerChangedEvent",
    "HungerComponent",
    "HungerSystem",
    "ThirstChangedEvent",
    "ThirstComponent",
    "ThirstSystem",
    "hunger_band",
    "thirst_band",
]
