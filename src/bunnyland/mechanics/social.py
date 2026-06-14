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
from relics import Component, Edge, Entity, EntityId, World

from ..core.components import AffectComponent, IdentityComponent
from ..core.ecs import entity_name, parse_entity_id, spawn_entity
from ..core.events import ConversationLineEvent, SpeechSaidEvent, SpeechToldEvent
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


@dataclass(frozen=True)
class GossipClaimComponent(Component):
    """A structured claim that can be remembered, attributed, and relayed."""

    text: str
    subject_id: str = ""
    source_character_id: str = ""
    source_event_id: str = ""
    created_at_epoch: int = 0


@dataclass(frozen=True)
class KnowsGossip(Edge):
    """character -> GossipClaim knowledge, with provenance and confidence."""

    confidence: float = 1.0
    learned_from_id: str = ""
    learned_at_epoch: int = 0
    hops: int = 0


@dataclass(frozen=True)
class SpeechInterpretation:
    """How one listener receives a speech act after mood and relationship bias."""

    base_interpretation: str
    final_interpretation: str
    relationship_tags: tuple[str, ...] = ()
    mood_tags: tuple[str, ...] = ()


_FIELDS = ("affinity", "trust", "fear", "resentment", "familiarity")
_FAMILIARITY_PER_SAY = 0.03
_FAMILIARITY_PER_TELL = 0.06
_SOCIAL_RECOVERY_PER_SAY = 8.0
_SOCIAL_RECOVERY_PER_TELL = 12.0
_GOSSIP_RELAY_FLOOR = 0.05
_GOSSIP_RELAY_CEILING = 0.9
_GOSSIP_PROMPT_LIMIT = 5

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

_WARM_INTENTS = frozenset({"praise", "comfort", "flirt", "apology", "offer", "promise", "joke"})


def _affect_labels(entity: Entity) -> set[str]:
    if not entity.has_component(AffectComponent):
        return set()
    affect = entity.get_component(AffectComponent)
    labels = set(affect.labels)
    if affect.current.anger >= 8:
        labels.add("angry")
    if affect.current.fear >= 10:
        labels.add("afraid")
    if affect.current.stress >= 10:
        labels.add("tense")
    return labels


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


def known_gossip(world: World, character_id: EntityId) -> list[tuple[Entity, KnowsGossip]]:
    """Return structured claims known by a character, newest and strongest first."""
    if not world.has_entity(character_id):
        return []
    known: list[tuple[Entity, KnowsGossip]] = []
    for edge, claim_id in world.get_entity(character_id).get_relationships(KnowsGossip):
        if not world.has_entity(claim_id):
            continue
        claim = world.get_entity(claim_id)
        if claim.has_component(GossipClaimComponent):
            known.append((claim, edge))
    return sorted(
        known,
        key=lambda item: (
            item[1].learned_at_epoch,
            item[1].confidence,
            item[0].get_component(GossipClaimComponent).text,
        ),
        reverse=True,
    )


def _knows_claim(world: World, character_id: EntityId, claim_id: EntityId) -> bool:
    if not world.has_entity(character_id):
        return False
    return any(
        target == claim_id
        for _edge, target in world.get_entity(character_id).get_relationships(KnowsGossip)
    )


def create_gossip_claim(
    world: World,
    *,
    text: str,
    subject_id: str = "",
    source_character_id: str = "",
    source_event_id: str = "",
    created_at_epoch: int = 0,
) -> Entity:
    """Spawn a claim entity so knowledge can be attributed without mutating prose."""
    return spawn_entity(
        world,
        [
            GossipClaimComponent(
                text=text.strip(),
                subject_id=subject_id,
                source_character_id=source_character_id,
                source_event_id=source_event_id,
                created_at_epoch=created_at_epoch,
            )
        ],
    )


def learn_gossip(
    world: World,
    learner_id: EntityId,
    claim_id: EntityId,
    *,
    learned_from_id: str = "",
    confidence: float = 1.0,
    hops: int = 0,
    learned_at_epoch: int = 0,
) -> bool:
    """Attach a structured claim to a learner, preserving the strongest known version."""
    if not world.has_entity(learner_id) or not world.has_entity(claim_id):
        return False
    claim = world.get_entity(claim_id)
    if not claim.has_component(GossipClaimComponent):
        return False
    learner = world.get_entity(learner_id)
    current = next(
        (edge for edge, target in learner.get_relationships(KnowsGossip) if target == claim_id),
        None,
    )
    if current is not None and current.confidence >= confidence and current.hops <= hops:
        return False
    learner.add_relationship(
        KnowsGossip(
            confidence=_clamp_confidence(confidence),
            learned_from_id=learned_from_id,
            learned_at_epoch=learned_at_epoch,
            hops=max(0, hops),
        ),
        claim_id,
    )
    return True


def interpret_speech_for_listener(
    world: World,
    speaker_id: EntityId,
    listener_id: EntityId,
    base_interpretation: str | None,
) -> SpeechInterpretation:
    """Contextualize a speech act for one listener.

    This is intentionally deterministic: the same authored sentence can land warmly with a
    trusting listener and badly with an angry, resentful listener, without letting raw text
    alone decide the result.
    """

    base = base_interpretation or "neutral"
    if not world.has_entity(listener_id):
        return SpeechInterpretation(base_interpretation=base, final_interpretation=base)
    listener = world.get_entity(listener_id)
    bond = bond_between(world, listener_id, speaker_id) or SocialBond()
    mood = _affect_labels(listener)
    relationship_tags: list[str] = []
    mood_tags: list[str] = sorted(mood)
    final = base

    hostile_bond = bond.resentment >= 0.5 or bond.fear >= 0.5 or bond.affinity <= -0.5
    trusting_bond = bond.trust >= 0.4 or bond.affinity >= 0.4
    agitated = bool(mood.intersection({"angry", "afraid", "tense"}))
    if hostile_bond:
        relationship_tags.append("hostile")
    if trusting_bond:
        relationship_tags.append("trusting")

    if base == "apology" and bond.resentment >= 0.5 and not trusting_bond:
        final = "neutral"
    elif base in _WARM_INTENTS and hostile_bond and agitated:
        final = "insult"
    elif base == "threat" and trusting_bond and not agitated:
        final = "joke"

    return SpeechInterpretation(
        base_interpretation=base,
        final_interpretation=final,
        relationship_tags=tuple(relationship_tags),
        mood_tags=tuple(mood_tags),
    )


class GossipReactor:
    """Creates and propagates structured gossip claims from conversation and speech."""

    def __init__(self, world: World) -> None:
        self.world = world

    def subscribe(self, bus) -> None:
        bus.subscribe(ConversationLineEvent, self._on_conversation_line)
        bus.subscribe(SpeechToldEvent, self._on_speech)
        bus.subscribe(SpeechSaidEvent, self._on_speech)

    def _on_conversation_line(self, event: ConversationLineEvent) -> None:
        speaker_id = parse_entity_id(event.speaker_id)
        if speaker_id is None or not self.world.has_entity(speaker_id):
            return
        speaker = self.world.get_entity(speaker_id)
        speaker_name = entity_name(speaker, "someone")
        claim = create_gossip_claim(
            self.world,
            text=f'{speaker_name} said in conversation {event.conversation_id}: "{event.text}"',
            subject_id=str(speaker_id),
            source_character_id=str(speaker_id),
            source_event_id=event.event_id,
            created_at_epoch=event.world_epoch,
        )
        learn_gossip(
            self.world,
            speaker_id,
            claim.id,
            confidence=1.0,
            learned_at_epoch=event.world_epoch,
        )
        for raw_target in event.target_ids:
            target_id = parse_entity_id(raw_target)
            if target_id is None or target_id == speaker_id or not self.world.has_entity(target_id):
                continue
            learn_gossip(
                self.world,
                target_id,
                claim.id,
                learned_from_id=str(speaker_id),
                confidence=1.0,
                learned_at_epoch=event.world_epoch,
            )

    def _on_speech(self, event: SpeechSaidEvent | SpeechToldEvent) -> None:
        if event.final_interpretation != "gossip":
            return
        speaker_id = parse_entity_id(event.actor_id) if event.actor_id else None
        if speaker_id is None or not self.world.has_entity(speaker_id):
            return
        claims = known_gossip(self.world, speaker_id)
        if not claims:
            return
        for raw_target in event.target_ids:
            target_id = parse_entity_id(raw_target)
            if target_id is None or target_id == speaker_id or not self.world.has_entity(target_id):
                continue
            for claim, edge in claims:
                if _knows_claim(self.world, target_id, claim.id):
                    continue
                confidence = edge.confidence * _relay_factor(self.world, speaker_id, target_id)
                learn_gossip(
                    self.world,
                    target_id,
                    claim.id,
                    learned_from_id=str(speaker_id),
                    confidence=confidence,
                    hops=edge.hops + 1,
                    learned_at_epoch=event.world_epoch,
                )


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
            interpretation = interpret_speech_for_listener(
                self.world,
                speaker,
                listener,
                intent,
            )
            listener_extra = _LISTENER_DELTAS.get(interpretation.final_interpretation, {})
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


def gossip_fragments(world: World, character: Entity) -> list[str]:
    """Foundation-prompt lines for structured hearsay known by a character."""
    lines: list[str] = []
    for claim, edge in known_gossip(world, character.id)[:_GOSSIP_PROMPT_LIMIT]:
        component = claim.get_component(GossipClaimComponent)
        if edge.learned_from_id:
            source_id = parse_entity_id(edge.learned_from_id)
            source = (
                entity_name(world.get_entity(source_id), "someone")
                if source_id is not None and world.has_entity(source_id)
                else "someone"
            )
            lines.append(
                f"You heard from {source}: {component.text} "
                f"(confidence {edge.confidence:.2f})."
            )
        else:
            lines.append(f"You know: {component.text} (confidence {edge.confidence:.2f}).")
    return sorted(lines)


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def _relay_factor(world: World, speaker_id: EntityId, listener_id: EntityId) -> float:
    bond = bond_between(world, listener_id, speaker_id) or SocialBond()
    factor = (
        0.45
        + 0.25 * bond.trust
        + 0.15 * bond.familiarity
        + 0.10 * bond.affinity
        - 0.20 * bond.fear
        - 0.20 * bond.resentment
    )
    return max(_GOSSIP_RELAY_FLOOR, min(_GOSSIP_RELAY_CEILING, factor))


def install_social(actor: WorldActor) -> None:
    """Wire the relationship reactor onto an actor's event bus."""
    RelationshipReactor(actor.world).subscribe(actor.bus)
    GossipReactor(actor.world).subscribe(actor.bus)


__all__ = [
    "GossipClaimComponent",
    "GossipReactor",
    "KnowsGossip",
    "RelationshipReactor",
    "SocialBond",
    "SpeechInterpretation",
    "adjust_bond",
    "bond_between",
    "create_gossip_claim",
    "gossip_fragments",
    "install_social",
    "interpret_speech_for_listener",
    "known_gossip",
    "learn_gossip",
    "relationship_fragments",
]
