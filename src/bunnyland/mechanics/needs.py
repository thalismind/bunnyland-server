"""Hunger and thirst: separate components, systems, and events (spec 9.4, 11.11, 23.3).

Hunger and thirst are deliberately distinct mechanics. Each rises over real time and is
relieved by a different action (eat vs drink). Both reuse the shared ``Meter`` primitive
but never share a component or system.

These systems are *harmful* world-participation systems, so they exclude suspended and
dead characters via their own queries (spec 8.1, 23.3).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pydantic.dataclasses import dataclass
from relics import Component, Frequency, System

from ..core.commands import SubmittedCommand
from ..core.components import DeadComponent, SleepingComponent, SuspendedComponent
from ..core.ecs import container_of, parse_entity_id, reachable_ids, replace_component
from ..core.events import DomainEvent
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
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


@dataclass(frozen=True)
class FatigueComponent(Component):
    meter: Meter = Meter()
    fatigue_rate: float = 1.0
    recovery_rate: float = 12.0
    last_recovered_epoch: int | None = None


@dataclass(frozen=True)
class HygieneComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.75
    last_cleaned_epoch: int | None = None


@dataclass(frozen=True)
class ComfortNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.5
    last_comforted_epoch: int | None = None


@dataclass(frozen=True)
class FunNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.5
    last_played_epoch: int | None = None


@dataclass(frozen=True)
class SocialNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.5
    last_social_epoch: int | None = None


@dataclass(frozen=True)
class PrivacyNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.25
    last_private_epoch: int | None = None


@dataclass(frozen=True)
class SafetyNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.25
    last_safe_epoch: int | None = None


@dataclass(frozen=True)
class NeedAffordanceComponent(Component):
    """Marks rooms/objects that make daily-life need recovery more effective."""

    recoveries: dict[str, float]
    label: str = ""


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


class DailyNeedChangedEvent(DomainEvent):
    need: str
    value: float
    band: str


class DailyNeedRecoveredEvent(DomainEvent):
    need: str
    recovery: float
    target_id: str | None = None


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


class FatigueSystem(System):
    """Raise fatigue while awake and recover it while sleeping."""

    def query(self):
        return self.q.with_all([FatigueComponent]).with_none([SuspendedComponent, DeadComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        hours = delta / SECONDS_PER_HOUR
        for entity in entities:
            fatigue = entity.get_component(FatigueComponent)
            rate = (
                -fatigue.recovery_rate
                if entity.has_component(SleepingComponent)
                else fatigue.fatigue_rate
            )
            new_meter = changed(fatigue.meter, rate * hours)
            if new_meter.value != fatigue.meter.value:
                replace_component(entity, replace(fatigue, meter=new_meter))


class HygieneSystem(System):
    def query(self):
        return self.q.with_all([HygieneComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        _rise_need(entities, HygieneComponent, "decay_rate", delta)


class ComfortNeedSystem(System):
    def query(self):
        return self.q.with_all([ComfortNeedComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        _rise_need(entities, ComfortNeedComponent, "decay_rate", delta)


class FunNeedSystem(System):
    def query(self):
        return self.q.with_all([FunNeedComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        _rise_need(entities, FunNeedComponent, "decay_rate", delta)


class SocialNeedSystem(System):
    def query(self):
        return self.q.with_all([SocialNeedComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        _rise_need(entities, SocialNeedComponent, "decay_rate", delta)


class PrivacyNeedSystem(System):
    def query(self):
        return self.q.with_all([PrivacyNeedComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        _rise_need(entities, PrivacyNeedComponent, "decay_rate", delta)


class SafetyNeedSystem(System):
    def query(self):
        return self.q.with_all([SafetyNeedComponent]).with_none(
            [SuspendedComponent, DeadComponent]
        )

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        _rise_need(entities, SafetyNeedComponent, "decay_rate", delta)


def _rise_need(entities, component_type, rate_field: str, delta: float) -> None:
    hours = delta / SECONDS_PER_HOUR
    for entity in entities:
        component = entity.get_component(component_type)
        new_meter = changed(component.meter, getattr(component, rate_field) * hours)
        if new_meter.value != component.meter.value:
            replace_component(entity, replace(component, meter=new_meter))


def hunger_band(entity) -> str:
    return band(entity.get_component(HungerComponent).meter)


def thirst_band(entity) -> str:
    return band(entity.get_component(ThirstComponent).meter)


def recover_daily_need(
    entity,
    component_type,
    amount: float,
    epoch: int,
    *,
    timestamp_field: str | None = None,
):
    component = entity.get_component(component_type)
    updates: dict[str, Any] = {"meter": changed(component.meter, -amount)}
    if timestamp_field is not None:
        updates[timestamp_field] = epoch
    updated = replace(component, **updates)
    replace_component(entity, updated)
    return updated


def _reachable_target(ctx: HandlerContext, character, target_id):
    if target_id is None:
        return None
    if target_id not in reachable_ids(ctx.world, character):
        return False
    return ctx.entity(target_id)


def _affordance_bonus(target, need: str) -> float:
    if target is None or target is False or not target.has_component(NeedAffordanceComponent):
        return 0.0
    return target.get_component(NeedAffordanceComponent).recoveries.get(need, 0.0)


class _RecoverNeedHandler:
    command_type = ""
    need = ""
    component_type = HungerComponent
    amount = 0.0
    timestamp_field: str | None = None
    target_payload_key = "target_id"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        if not ctx.world.has_entity(character_id):
            return rejected("character does not exist")
        character = ctx.entity(character_id)
        if not character.has_component(self.component_type):
            return rejected(f"character has no {self.need} need")

        target_id = parse_entity_id(command.payload.get(self.target_payload_key))
        target = _reachable_target(ctx, character, target_id)
        if target is False:
            return rejected("target is not reachable")

        recovery = self.amount + _affordance_bonus(target, self.need)
        updated = recover_daily_need(
            character,
            self.component_type,
            recovery,
            ctx.epoch,
            timestamp_field=self.timestamp_field,
        )
        return ok(
            DailyNeedRecoveredEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(container_of(character)),
                    target_ids=(str(target_id),) if target_id is not None else (),
                    need=self.need,
                    recovery=recovery,
                    target_id=str(target_id) if target_id is not None else None,
                )
            ),
            DailyNeedChangedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    need=self.need,
                    value=updated.meter.value,
                    band=band(updated.meter),
                )
            ),
        )


class BatheHandler(_RecoverNeedHandler):
    command_type = "bathe"
    need = "hygiene"
    component_type = HygieneComponent
    amount = 35.0
    timestamp_field = "last_cleaned_epoch"


class CleanSelfHandler(_RecoverNeedHandler):
    command_type = "clean-self"
    need = "hygiene"
    component_type = HygieneComponent
    amount = 15.0
    timestamp_field = "last_cleaned_epoch"


class PlayHandler(_RecoverNeedHandler):
    command_type = "play"
    need = "fun"
    component_type = FunNeedComponent
    amount = 25.0
    timestamp_field = "last_played_epoch"


class RelaxHandler(_RecoverNeedHandler):
    command_type = "relax"
    need = "comfort"
    component_type = ComfortNeedComponent
    amount = 25.0
    timestamp_field = "last_comforted_epoch"


class SeekPrivacyHandler(_RecoverNeedHandler):
    command_type = "seek-privacy"
    need = "privacy"
    component_type = PrivacyNeedComponent
    amount = 30.0
    timestamp_field = "last_private_epoch"


class SeekSafetyHandler(_RecoverNeedHandler):
    command_type = "seek-safety"
    need = "safety"
    component_type = SafetyNeedComponent
    amount = 30.0
    timestamp_field = "last_safe_epoch"


_HUNGER_PHRASES = {
    "warning": "You are getting hungry.",
    "urgent": "You are hungry; food is becoming a priority.",
    "crisis": "You are starving and feel weak.",
}
_THIRST_PHRASES = {
    "warning": "Your mouth is dry.",
    "urgent": "You are thirsty; you should find clean water soon.",
    "crisis": "You are dehydrated, dizzy, and unfocused.",
}
_DAILY_NEED_PHRASES = {
    FatigueComponent: {
        "warning": "You are getting tired.",
        "urgent": "You are fatigued and should rest soon.",
        "crisis": "You are exhausted and badly need sleep.",
    },
    HygieneComponent: {
        "warning": "You feel a little grimy.",
        "urgent": "You need to bathe or clean yourself.",
        "crisis": "You feel filthy and uncomfortable.",
    },
    ComfortNeedComponent: {
        "warning": "You want somewhere more comfortable.",
        "urgent": "Discomfort is wearing on you.",
        "crisis": "You are deeply uncomfortable.",
    },
    FunNeedComponent: {
        "warning": "You could use something fun to do.",
        "urgent": "Boredom is becoming hard to ignore.",
        "crisis": "You are miserable from boredom.",
    },
    SocialNeedComponent: {
        "warning": "You could use some company.",
        "urgent": "You feel lonely and need conversation.",
        "crisis": "Isolation is weighing heavily on you.",
    },
    PrivacyNeedComponent: {
        "warning": "You could use a little privacy.",
        "urgent": "You need space away from others.",
        "crisis": "You feel overwhelmed and need privacy now.",
    },
    SafetyNeedComponent: {
        "warning": "You feel a little unsafe.",
        "urgent": "You need to get somewhere safe.",
        "crisis": "You feel exposed to immediate danger.",
    },
}


def need_fragments(world, character) -> list[str]:
    """Prompt phrases for this character's pressing needs (spec 16.3, 27.1)."""
    del world  # signature matches the builder's fragment-provider protocol
    fragments: list[str] = []
    if character.has_component(HungerComponent):
        phrase = _HUNGER_PHRASES.get(hunger_band(character))
        if phrase:
            fragments.append(phrase)
    if character.has_component(ThirstComponent):
        phrase = _THIRST_PHRASES.get(thirst_band(character))
        if phrase:
            fragments.append(phrase)
    for component_type, phrases in _DAILY_NEED_PHRASES.items():
        if not character.has_component(component_type):
            continue
        phrase = phrases.get(band(character.get_component(component_type).meter))
        if phrase:
            fragments.append(phrase)
    return fragments


__all__ = [
    "BatheHandler",
    "CleanSelfHandler",
    "ComfortNeedComponent",
    "ComfortNeedSystem",
    "DailyNeedChangedEvent",
    "DailyNeedRecoveredEvent",
    "DrinkConsumedEvent",
    "FatigueComponent",
    "FatigueSystem",
    "FoodEatenEvent",
    "FunNeedComponent",
    "FunNeedSystem",
    "HygieneComponent",
    "HygieneSystem",
    "HungerChangedEvent",
    "HungerComponent",
    "HungerSystem",
    "NeedAffordanceComponent",
    "PlayHandler",
    "PrivacyNeedComponent",
    "PrivacyNeedSystem",
    "RelaxHandler",
    "SafetyNeedComponent",
    "SafetyNeedSystem",
    "SeekPrivacyHandler",
    "SeekSafetyHandler",
    "SocialNeedComponent",
    "SocialNeedSystem",
    "ThirstChangedEvent",
    "ThirstComponent",
    "ThirstSystem",
    "hunger_band",
    "need_fragments",
    "recover_daily_need",
    "thirst_band",
]
