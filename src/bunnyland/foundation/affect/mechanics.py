"""Affect and thoughts (spec 11.12, 14.3, 23.5).

Events produce *thoughts* — small, decaying entities carrying an ``AffectDelta`` — which
aggregate into a character's current multidimensional mood. Mood is never a single
scalar; coarse feeling *labels* are derived for prompts.

Two pieces:
- ``AffectReactor`` subscribes to domain events and creates thoughts on the affected
  characters (e.g. an insult heard, a good meal, being downed).
- ``AffectAggregation`` is a post-command consequence that expires old thoughts and
  recomputes ``current = baseline + sum(active deltas)`` and the feeling labels.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import TYPE_CHECKING

from relics import World

from bunnyland.foundation.needs.mechanics import FoodEatenEvent

from ...core.components import (
    AffectComponent,
    AffectDelta,
    AffectVector,
    CharacterComponent,
    ThoughtComponent,
)
from ...core.ecs import replace_component, spawn_entity
from ...core.edges import HasThought
from ...core.events import (
    AffectChangedEvent,
    CharacterDownedEvent,
    DomainEvent,
    SpeechSaidEvent,
)

if TYPE_CHECKING:
    from ...core.world_actor import WorldActor

#: How long a thought lingers before it decays (game seconds; tuning, not architecture).
THOUGHT_TTL_SECONDS = 4 * 3600

_DIMENSIONS = tuple(f.name for f in fields(AffectVector))

# Thresholds mapping an affect dimension value to a feeling label (tuning data).
_LABEL_RULES: tuple[tuple[str, str, float], ...] = (
    ("stress", "tense", 10.0),
    ("fear", "afraid", 10.0),
    ("anger", "angry", 8.0),
    ("sadness", "sad", 8.0),
    ("curiosity", "curious", 8.0),
    ("valence", "content", 8.0),
    ("valence", "unhappy", -8.0),
)


def apply_delta(vector: AffectVector, delta: AffectDelta) -> AffectVector:
    return AffectVector(**{d: getattr(vector, d) + getattr(delta, d) for d in _DIMENSIONS})


def labels_for(vector: AffectVector) -> tuple[str, ...]:
    labels: list[str] = []
    for dimension, label, threshold in _LABEL_RULES:
        value = getattr(vector, dimension)
        if threshold >= 0 and value >= threshold:
            labels.append(label)
        elif threshold < 0 and value <= threshold:
            labels.append(label)
    return tuple(sorted(labels))


# Interpretation -> (label, text, delta) for speech a character hears.
_SPEECH_REACTIONS: dict[str, tuple[str, str, AffectDelta]] = {
    "insult": ("insulted", "That stung.", AffectDelta(valence=-10, anger=8, sadness=3)),
    "threat": ("threatened", "I feel threatened.", AffectDelta(fear=10, stress=8)),
    "praise": ("flattered", "That was kind.", AffectDelta(valence=8, confidence=4)),
    "comfort": ("comforted", "I feel a little better.", AffectDelta(valence=5, stress=-5)),
}


class AffectReactor:
    """Creates thoughts on characters in response to events (spec 14.3)."""

    def __init__(self, world: World) -> None:
        self.world = world

    def subscribe(self, bus) -> None:
        bus.subscribe(FoodEatenEvent, self._on_food)
        bus.subscribe(SpeechSaidEvent, self._on_speech)
        bus.subscribe(CharacterDownedEvent, self._on_downed)

    def _add_thought(self, character_id_str, label, text, delta, epoch, source_event_id):
        from ...core.ecs import parse_entity_id

        character_id = parse_entity_id(character_id_str)
        if character_id is None or not self.world.has_entity(character_id):
            return
        character = self.world.get_entity(character_id)
        if not character.has_component(CharacterComponent):
            return
        thought = spawn_entity(
            self.world,
            [
                ThoughtComponent(
                    label=label,
                    text=text,
                    affect_delta=delta,
                    created_at_epoch=epoch,
                    expires_at_epoch=epoch + THOUGHT_TTL_SECONDS,
                    source_event_id=source_event_id,
                )
            ],
        )
        character.add_relationship(HasThought(), thought.id)

    def _on_food(self, event: FoodEatenEvent) -> None:
        self._add_thought(
            event.actor_id,
            "satisfied",
            "That was a good meal.",
            AffectDelta(valence=8, stress=-3),
            event.world_epoch,
            event.event_id,
        )

    def _on_speech(self, event: SpeechSaidEvent) -> None:
        from bunnyland.foundation.social.mechanics import interpret_speech_for_listener

        from ...core.ecs import parse_entity_id

        speaker = parse_entity_id(event.actor_id) if event.actor_id else None
        for hearer in event.target_ids:
            listener = parse_entity_id(hearer)
            if speaker is not None and listener is not None:
                interpretation = interpret_speech_for_listener(
                    self.world,
                    speaker,
                    listener,
                    event.final_interpretation,
                )
                final_interpretation = interpretation.final_interpretation
            else:
                final_interpretation = event.final_interpretation or ""
            reaction = _SPEECH_REACTIONS.get(final_interpretation)
            if reaction is None:
                continue
            label, text, delta = reaction
            self._add_thought(hearer, label, text, delta, event.world_epoch, event.event_id)

    def _on_downed(self, event: CharacterDownedEvent) -> None:
        self._add_thought(
            event.actor_id,
            "in pain",
            "Everything hurts.",
            AffectDelta(fear=10, stress=12, valence=-8),
            event.world_epoch,
            event.event_id,
        )


class AffectAggregation:
    """Expire thoughts and recompute current mood + labels (consequence, spec 23.5)."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all([AffectComponent])
        for character in query.execute_entities():
            affect = character.get_component(AffectComponent)
            current = affect.baseline
            for edge_thought_id in list(character.get_relationships(HasThought)):
                _edge, thought_id = edge_thought_id
                thought = world.get_entity(thought_id)
                tc = thought.get_component(ThoughtComponent)
                if tc.expires_at_epoch is not None and epoch >= tc.expires_at_epoch:
                    character.remove_relationship(HasThought, thought_id)
                    world.remove(thought_id)
                    continue
                current = apply_delta(current, tc.affect_delta)
            labels = labels_for(current)
            if current != affect.current or labels != affect.labels:
                replace_component(character, replace(affect, current=current, labels=labels))
                if labels != affect.labels:
                    events.append(
                        AffectChangedEvent(
                            event_id=_uuid(),
                            world_epoch=epoch,
                            created_at=_now(),
                            actor_id=str(character.id),
                            labels=tuple(sorted(labels)),
                        )
                    )
        return events


def _uuid() -> str:
    from uuid import uuid4

    return uuid4().hex


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def install_affect(actor: WorldActor) -> None:
    """Wire the affect reactor (events -> thoughts) and aggregation consequence."""
    reactor = AffectReactor(actor.world)
    reactor.subscribe(actor.bus)
    actor.register_consequence(AffectAggregation())


__all__ = [
    "AffectAggregation",
    "AffectReactor",
    "apply_delta",
    "install_affect",
    "labels_for",
]
