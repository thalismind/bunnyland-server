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

from bunnyland.foundation.meters.mechanics import Meter, band, changed

from ...core.commands import SubmittedCommand
from ...core.components import DeadComponent, SleepingComponent, SuspendedComponent
from ...core.ecs import container_of, parse_entity_id, replace_component
from ...core.events import DomainEvent
from ...core.handlers import (
    HandlerContext,
    HandlerResult,
    planned,
    rejected,
    require_character,
    require_reachable_entity,
)
from ...core.mutations import MutationPlan, SetComponent
from ...prompts import ComponentPromptContext, PerspectivePhrase, PromptFact, PromptPerspective

SECONDS_PER_HOUR = 3600.0


# --------------------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HungerComponent(Component):
    meter: Meter = Meter()
    metabolism: float = 1.0  # hunger points gained per game hour
    last_ate_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _meter_fact(
            ctx,
            self.meter,
            "needs.hunger",
            _HUNGER_PROMPT_PHRASES,
            observable_cutoff=10,
        )


@dataclass(frozen=True)
class ThirstComponent(Component):
    meter: Meter = Meter()
    hydration_loss_rate: float = 1.5  # thirst points gained per game hour
    last_drank_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _meter_fact(
            ctx,
            self.meter,
            "needs.thirst",
            _THIRST_PROMPT_PHRASES,
            observable_cutoff=10,
        )


@dataclass(frozen=True)
class FatigueComponent(Component):
    meter: Meter = Meter()
    fatigue_rate: float = 1.0
    recovery_rate: float = 12.0
    last_recovered_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _daily_need_fragments(ctx, self)


@dataclass(frozen=True)
class HygieneComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.75
    last_cleaned_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _daily_need_fragments(ctx, self)


@dataclass(frozen=True)
class ComfortNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.5
    last_comforted_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _daily_need_fragments(ctx, self)


@dataclass(frozen=True)
class FunNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.5
    last_played_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _daily_need_fragments(ctx, self)


@dataclass(frozen=True)
class SocialNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.5
    last_social_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _daily_need_fragments(ctx, self)


@dataclass(frozen=True)
class PrivacyNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.25
    last_private_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _daily_need_fragments(ctx, self)


@dataclass(frozen=True)
class SafetyNeedComponent(Component):
    meter: Meter = Meter()
    decay_rate: float = 0.25
    last_safe_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[PromptFact, ...]:
        return _daily_need_fragments(ctx, self)


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
        return self.q.with_all([HungerComponent]).with_none([SuspendedComponent, DeadComponent])

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
        return self.q.with_all([ThirstComponent]).with_none([SuspendedComponent, DeadComponent])

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
        return self.q.with_all([HygieneComponent]).with_none([SuspendedComponent, DeadComponent])

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
        return self.q.with_all([FunNeedComponent]).with_none([SuspendedComponent, DeadComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        _rise_need(entities, FunNeedComponent, "decay_rate", delta)


class SocialNeedSystem(System):
    def query(self):
        return self.q.with_all([SocialNeedComponent]).with_none([SuspendedComponent, DeadComponent])

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
        return self.q.with_all([SafetyNeedComponent]).with_none([SuspendedComponent, DeadComponent])

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
    updated = recovered_daily_need(
        entity,
        component_type,
        amount,
        epoch,
        timestamp_field=timestamp_field,
    )
    replace_component(entity, updated)
    return updated


def recovered_daily_need(
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
    return updated


def _affordance_bonus(target, need: str) -> float:
    if target is None or not target.has_component(NeedAffordanceComponent):
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
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if not character.has_component(self.component_type):
            return rejected(f"character has no {self.need} need")

        target_id = parse_entity_id(command.payload.get(self.target_payload_key))
        target = None
        if target_id is not None:
            _, target, error = require_reachable_entity(
                ctx,
                character,
                target_id,
                invalid_reason="invalid target id",
                missing_reason="target does not exist",
                unreachable_reason="target is not reachable",
            )
            if error is not None:
                return error

        recovery = self.amount + _affordance_bonus(target, self.need)
        updated = recovered_daily_need(
            character,
            self.component_type,
            recovery,
            ctx.epoch,
            timestamp_field=self.timestamp_field,
        )
        return planned(
            MutationPlan((SetComponent(character_id, updated),)),
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
_HUNGER_PROMPT_PHRASES = {
    "calm": PerspectivePhrase("I am not hungry.", "You are not hungry.", "They are not hungry."),
    "warning": PerspectivePhrase(
        "I am getting hungry.",
        _HUNGER_PHRASES["warning"],
        "They are getting hungry.",
    ),
    "urgent": PerspectivePhrase(
        "I am hungry; food is becoming a priority.",
        _HUNGER_PHRASES["urgent"],
        "They are hungry; food is becoming a priority.",
    ),
    "crisis": PerspectivePhrase(
        "I am starving and feel weak.",
        _HUNGER_PHRASES["crisis"],
        "They are starving and feel weak.",
    ),
}
_THIRST_PROMPT_PHRASES = {
    "calm": PerspectivePhrase("I am not thirsty.", "You are not thirsty.", "They are not thirsty."),
    "warning": PerspectivePhrase(
        "My mouth is dry.",
        _THIRST_PHRASES["warning"],
        "Their mouth is dry.",
    ),
    "urgent": PerspectivePhrase(
        "I am thirsty; I should find clean water soon.",
        _THIRST_PHRASES["urgent"],
        "They are thirsty; they should find clean water soon.",
    ),
    "crisis": PerspectivePhrase(
        "I am dehydrated, dizzy, and unfocused.",
        _THIRST_PHRASES["crisis"],
        "They are dehydrated, dizzy, and unfocused.",
    ),
}
_DAILY_NEED_PROMPT_PHRASES = {
    FatigueComponent: {
        "calm": PerspectivePhrase("I feel rested.", "You feel rested.", "They feel rested."),
        "warning": PerspectivePhrase(
            "I am getting tired.",
            _DAILY_NEED_PHRASES[FatigueComponent]["warning"],
            "They are getting tired.",
        ),
        "urgent": PerspectivePhrase(
            "I am fatigued and should rest soon.",
            _DAILY_NEED_PHRASES[FatigueComponent]["urgent"],
            "They are fatigued and should rest soon.",
        ),
        "crisis": PerspectivePhrase(
            "I am exhausted and badly need sleep.",
            _DAILY_NEED_PHRASES[FatigueComponent]["crisis"],
            "They are exhausted and badly need sleep.",
        ),
    },
    HygieneComponent: {
        "calm": PerspectivePhrase("I feel clean.", "You feel clean.", "They feel clean."),
        "warning": PerspectivePhrase(
            "I feel a little grimy.",
            _DAILY_NEED_PHRASES[HygieneComponent]["warning"],
            "They feel a little grimy.",
        ),
        "urgent": PerspectivePhrase(
            "I need to bathe or clean myself.",
            _DAILY_NEED_PHRASES[HygieneComponent]["urgent"],
            "They need to bathe or clean themselves.",
        ),
        "crisis": PerspectivePhrase(
            "I feel filthy and uncomfortable.",
            _DAILY_NEED_PHRASES[HygieneComponent]["crisis"],
            "They feel filthy and uncomfortable.",
        ),
    },
    ComfortNeedComponent: {
        "calm": PerspectivePhrase(
            "I feel comfortable.", "You feel comfortable.", "They feel comfortable."
        ),
        "warning": PerspectivePhrase(
            "I want somewhere more comfortable.",
            _DAILY_NEED_PHRASES[ComfortNeedComponent]["warning"],
            "They want somewhere more comfortable.",
        ),
        "urgent": PerspectivePhrase(
            "Discomfort is wearing on me.",
            _DAILY_NEED_PHRASES[ComfortNeedComponent]["urgent"],
            "Discomfort is wearing on them.",
        ),
        "crisis": PerspectivePhrase(
            "I am deeply uncomfortable.",
            _DAILY_NEED_PHRASES[ComfortNeedComponent]["crisis"],
            "They are deeply uncomfortable.",
        ),
    },
    FunNeedComponent: {
        "calm": PerspectivePhrase("I feel engaged.", "You feel engaged.", "They feel engaged."),
        "warning": PerspectivePhrase(
            "I could use something fun to do.",
            _DAILY_NEED_PHRASES[FunNeedComponent]["warning"],
            "They could use something fun to do.",
        ),
        "urgent": PerspectivePhrase(
            "Boredom is becoming hard to ignore.",
            _DAILY_NEED_PHRASES[FunNeedComponent]["urgent"],
            "Boredom is becoming hard for them to ignore.",
        ),
        "crisis": PerspectivePhrase(
            "I am miserable from boredom.",
            _DAILY_NEED_PHRASES[FunNeedComponent]["crisis"],
            "They are miserable from boredom.",
        ),
    },
    SocialNeedComponent: {
        "calm": PerspectivePhrase(
            "I feel socially fulfilled.",
            "You feel socially fulfilled.",
            "They feel socially fulfilled.",
        ),
        "warning": PerspectivePhrase(
            "I could use some company.",
            _DAILY_NEED_PHRASES[SocialNeedComponent]["warning"],
            "They could use some company.",
        ),
        "urgent": PerspectivePhrase(
            "I feel lonely and need conversation.",
            _DAILY_NEED_PHRASES[SocialNeedComponent]["urgent"],
            "They feel lonely and need conversation.",
        ),
        "crisis": PerspectivePhrase(
            "Isolation is weighing heavily on me.",
            _DAILY_NEED_PHRASES[SocialNeedComponent]["crisis"],
            "Isolation is weighing heavily on them.",
        ),
    },
    PrivacyNeedComponent: {
        "calm": PerspectivePhrase(
            "I have enough privacy.", "You have enough privacy.", "They have enough privacy."
        ),
        "warning": PerspectivePhrase(
            "I could use a little privacy.",
            _DAILY_NEED_PHRASES[PrivacyNeedComponent]["warning"],
            "They could use a little privacy.",
        ),
        "urgent": PerspectivePhrase(
            "I need space away from others.",
            _DAILY_NEED_PHRASES[PrivacyNeedComponent]["urgent"],
            "They need space away from others.",
        ),
        "crisis": PerspectivePhrase(
            "I feel overwhelmed and need privacy now.",
            _DAILY_NEED_PHRASES[PrivacyNeedComponent]["crisis"],
            "They feel overwhelmed and need privacy now.",
        ),
    },
    SafetyNeedComponent: {
        "calm": PerspectivePhrase("I feel safe.", "You feel safe.", "They feel safe."),
        "warning": PerspectivePhrase(
            "I feel a little unsafe.",
            _DAILY_NEED_PHRASES[SafetyNeedComponent]["warning"],
            "They feel a little unsafe.",
        ),
        "urgent": PerspectivePhrase(
            "I need to get somewhere safe.",
            _DAILY_NEED_PHRASES[SafetyNeedComponent]["urgent"],
            "They need to get somewhere safe.",
        ),
        "crisis": PerspectivePhrase(
            "I feel exposed to immediate danger.",
            _DAILY_NEED_PHRASES[SafetyNeedComponent]["crisis"],
            "They feel exposed to immediate danger.",
        ),
    },
}


def _need_phrase(ctx: ComponentPromptContext, phrase: PerspectivePhrase) -> str:
    return phrase.render(ctx.perspective)


_DETAIL_BY_BAND = {"crisis": 0, "urgent": 10, "warning": 20, "calm": 30}


def _meter_fact(
    ctx: ComponentPromptContext,
    meter: Meter,
    key: str,
    phrases: dict[str, PerspectivePhrase],
    observable_cutoff: int | None = None,
) -> tuple[PromptFact, ...]:
    current_band = band(meter)
    detail = _DETAIL_BY_BAND[current_band]
    if not ctx.includes_detail(detail):
        return ()
    if not ctx.is_first_person and (observable_cutoff is None or detail > observable_cutoff):
        return ()
    phrase = _need_phrase(ctx, phrases[current_band])
    return (PromptFact(key=key, text=phrase, detail=detail),)


def _daily_need_fragments(
    ctx: ComponentPromptContext, component: Component
) -> tuple[PromptFact, ...]:
    component_name = type(component).__name__.removesuffix("Component").lower()
    return _meter_fact(
        ctx,
        component.meter,
        f"needs.{component_name}",
        _DAILY_NEED_PROMPT_PHRASES[type(component)],
    )


def need_fragments(
    world,
    character,
    *,
    detail_cutoff: int = 10,
    viewer=None,
) -> list[PromptFact]:
    """Prompt phrases for this character's pressing needs (spec 16.3, 27.1)."""
    fragments: list[PromptFact] = []
    ctx = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(
            viewer=viewer or character,
            perspective=(
                "second-person" if viewer is None or viewer.id == character.id else "third-person"
            ),
        ),
        detail_cutoff=detail_cutoff,
    )
    if character.has_component(HungerComponent):
        fragments.extend(character.get_component(HungerComponent).prompt_fragments(ctx))
    if character.has_component(ThirstComponent):
        fragments.extend(character.get_component(ThirstComponent).prompt_fragments(ctx))
    for component_type, phrases in _DAILY_NEED_PHRASES.items():
        del phrases
        if not character.has_component(component_type):
            continue
        fragments.extend(character.get_component(component_type).prompt_fragments(ctx))
    return fragments


def install_needs(actor) -> None:
    """Install Foundation need systems and their associated action handlers."""

    from bunnyland.foundation.consumables.actions import DrinkHandler, EatHandler

    for system_type in (
        HungerSystem,
        ThirstSystem,
        FatigueSystem,
        HygieneSystem,
        ComfortNeedSystem,
        FunNeedSystem,
        SocialNeedSystem,
        PrivacyNeedSystem,
        SafetyNeedSystem,
    ):
        actor.world.register_system(system_type())
    for handler_type in (
        EatHandler,
        DrinkHandler,
        BatheHandler,
        CleanSelfHandler,
        PlayHandler,
        RelaxHandler,
        SeekPrivacyHandler,
        SeekSafetyHandler,
    ):
        actor.register_handler(handler_type())


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
    "install_needs",
    "need_fragments",
    "recover_daily_need",
    "thirst_band",
]
