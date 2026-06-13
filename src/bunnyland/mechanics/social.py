"""Social bonds between characters (spec 11.15).

Characters form directed ``SocialBond`` edges (affinity / trust / fear / resentment /
familiarity). Talking builds them: every utterance heard grows familiarity both ways, and
the speech's intent nudges the rest — praise and comfort warm a bond, threats frighten the
listener, insults breed resentment. Bonds are surfaced in the foundation prompt so an agent
knows who it likes, trusts, or fears (a prompt fragment provider, spec 16.3).

This is the speech->relationship layer that complements affect (mood): affect is how a
character feels overall; bonds are how it feels about specific others.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic.dataclasses import dataclass
from relics import Edge, Entity, EntityId, World

from ..core.components import IdentityComponent
from ..core.ecs import parse_entity_id
from ..core.events import SpeechSaidEvent, SpeechToldEvent
from ..prompts import ComponentPromptContext
from .needs import SocialNeedComponent, recover_daily_need

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


@dataclass(frozen=True)
class SocialBond(Edge):
    """How one character feels about another (directed)."""

    affinity: float = 0.0
    trust: float = 0.0
    fear: float = 0.0
    resentment: float = 0.0
    familiarity: float = 0.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        if ctx.target is None:
            return ()
        descriptor = _describe_bond(self, ctx.perspective.perspective)
        if descriptor is None:
            return ()
        name = (
            ctx.target.get_component(IdentityComponent).name
            if ctx.target.has_component(IdentityComponent)
            else "someone"
        )
        subject = ctx.perspective.choose(first="I", second="You", third="They")
        return (f"{subject} {descriptor} {name}.",)


_FIELDS = ("affinity", "trust", "fear", "resentment", "familiarity")
_FAMILIARITY_PER_SAY = 0.03
_FAMILIARITY_PER_TELL = 0.06
_SOCIAL_RECOVERY_PER_SAY = 8.0
_SOCIAL_RECOVERY_PER_TELL = 12.0

# How the speaker's bond toward a listener shifts, by speech intent (spec 14.2).
_SPEAKER_DELTAS: dict[str, dict[str, float]] = {
    "praise": {"affinity": 0.10, "trust": 0.05},
    "comfort": {"affinity": 0.08, "trust": 0.05},
    "flirt": {"affinity": 0.12},
    "apology": {"affinity": 0.05},
    "offer": {"affinity": 0.05, "trust": 0.03},
    "promise": {"trust": 0.08},
    "joke": {"affinity": 0.04},
    "insult": {"affinity": -0.10, "resentment": 0.10},
    "threat": {"affinity": -0.05, "resentment": 0.08},
}
# How a listener's bond toward the speaker reacts.
_LISTENER_DELTAS: dict[str, dict[str, float]] = {
    "praise": {"affinity": 0.10, "trust": 0.04},
    "comfort": {"affinity": 0.08, "trust": 0.04},
    "flirt": {"affinity": 0.08},
    "apology": {"affinity": 0.06, "resentment": -0.10},
    "offer": {"affinity": 0.04, "trust": 0.03},
    "promise": {"trust": 0.06},
    "joke": {"affinity": 0.05},
    "insult": {"affinity": -0.10, "resentment": 0.12},
    "threat": {"fear": 0.15, "resentment": 0.10, "affinity": -0.08},
}


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def bond_between(world: World, source_id: EntityId, target_id: EntityId) -> SocialBond | None:
    """The directed ``source -> target`` bond, or ``None`` if they've never interacted."""
    for edge, target in world.get_entity(source_id).get_relationships(SocialBond):
        if target == target_id:
            return edge
    return None


def adjust_bond(
    world: World, source_id: EntityId, target_id: EntityId, deltas: dict[str, float]
) -> SocialBond:
    """Apply ``deltas`` to the source->target bond (created if absent), clamped to [-1, 1]."""
    current = bond_between(world, source_id, target_id) or SocialBond()
    updated = SocialBond(
        **{field: _clamp(getattr(current, field) + deltas.get(field, 0.0)) for field in _FIELDS}
    )
    # add_relationship overwrites an existing edge of the same type+target.
    world.get_entity(source_id).add_relationship(updated, target_id)
    return updated


class RelationshipReactor:
    """Grows social bonds from speech events (subscribed to the event bus)."""

    def __init__(self, world: World) -> None:
        self.world = world

    def subscribe(self, bus) -> None:
        bus.subscribe(SpeechSaidEvent, self._on_speech)
        bus.subscribe(SpeechToldEvent, self._on_speech)

    def _on_speech(self, event: SpeechSaidEvent | SpeechToldEvent) -> None:
        speaker = parse_entity_id(event.actor_id) if event.actor_id else None
        if speaker is None or not self.world.has_entity(speaker):
            return
        familiarity = (
            _FAMILIARITY_PER_TELL if isinstance(event, SpeechToldEvent) else _FAMILIARITY_PER_SAY
        )
        recovery = (
            _SOCIAL_RECOVERY_PER_TELL
            if isinstance(event, SpeechToldEvent)
            else _SOCIAL_RECOVERY_PER_SAY
        )
        intent = event.final_interpretation or "neutral"
        speaker_extra = _SPEAKER_DELTAS.get(intent, {})
        listener_extra = _LISTENER_DELTAS.get(intent, {})
        speaker_entity = self.world.get_entity(speaker)
        if event.target_ids and speaker_entity.has_component(SocialNeedComponent):
            recover_daily_need(
                speaker_entity,
                SocialNeedComponent,
                recovery,
                event.world_epoch,
                timestamp_field="last_social_epoch",
            )

        for raw in event.target_ids:
            listener = parse_entity_id(raw)
            if listener is None or listener == speaker or not self.world.has_entity(listener):
                continue
            listener_entity = self.world.get_entity(listener)
            if listener_entity.has_component(SocialNeedComponent):
                recover_daily_need(
                    listener_entity,
                    SocialNeedComponent,
                    recovery,
                    event.world_epoch,
                    timestamp_field="last_social_epoch",
                )
            adjust_bond(
                self.world, speaker, listener, {**speaker_extra, "familiarity": familiarity}
            )
            adjust_bond(
                self.world, listener, speaker, {**listener_extra, "familiarity": familiarity}
            )


def _describe_bond(bond: SocialBond, perspective: str = "second-person") -> str | None:
    first_person = perspective == "first-person"
    if bond.fear >= 0.3:
        return "fear"
    if bond.resentment >= 0.3:
        return "resent"
    if bond.affinity >= 0.3:
        if first_person:
            return "am fond of"
        return "are fond of"
    if bond.affinity <= -0.3:
        return "dislike"
    if bond.familiarity >= 0.3:
        return "know"
    return None


def relationship_fragments(world: World, character: Entity) -> list[str]:
    """Foundation-prompt lines for the character's notable bonds."""
    lines: list[str] = []
    for bond, target_id in character.get_relationships(SocialBond):
        if not world.has_entity(target_id):
            continue
        target = world.get_entity(target_id)
        ctx = ComponentPromptContext.for_entity(world, character, target=target)
        lines.extend(bond.prompt_fragments(ctx))
    return sorted(lines)


def install_social(actor: WorldActor) -> None:
    """Wire the relationship reactor onto an actor's event bus."""
    RelationshipReactor(actor.world).subscribe(actor.bus)


__all__ = [
    "RelationshipReactor",
    "SocialBond",
    "adjust_bond",
    "bond_between",
    "install_social",
    "relationship_fragments",
]
