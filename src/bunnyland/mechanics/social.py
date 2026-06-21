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

from ..core.commands import SubmittedCommand
from ..core.components import AffectComponent, IdentityComponent
from ..core.ecs import entity_name, parse_entity_id, replace_component, spawn_entity
from ..core.events import (
    ConversationLineEvent,
    DomainEvent,
    EventVisibility,
    SpeechSaidEvent,
    SpeechToldEvent,
)
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
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
class ObligationComponent(Component):
    """A promise, request, offer, threat, debt, or agreement tracked as state."""

    kind: str
    text: str
    status: str = "open"
    source_event_id: str = ""
    created_at_epoch: int = 0
    due_epoch: int = 0
    resolved_at_epoch: int = 0
    resolution_note: str = ""


@dataclass(frozen=True)
class ObligationDebtor(Edge):
    role: str = "debtor"


@dataclass(frozen=True)
class ObligationCreditor(Edge):
    role: str = "creditor"


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
_OBLIGATION_PROMPT_LIMIT = 5
_OBLIGATION_INTENTS = frozenset({"offer", "promise", "request", "threat"})
_OBLIGATION_RESOLUTIONS = frozenset({"fulfilled", "failed", "canceled"})

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
    # get_relationships only yields live targets: world.remove() cascades incoming edges, so a
    # dangling claim_id can't appear here.
    for edge, claim_id in world.get_entity(character_id).get_relationships(KnowsGossip):
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
    # Only ever called for a character the caller has already confirmed exists.
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


def obligation_for_source(
    world: World, source_event_id: str, debtor_id: EntityId, creditor_id: EntityId
) -> Entity | None:
    for entity in world.query().with_all([ObligationComponent]).execute_entities():
        component = entity.get_component(ObligationComponent)
        if component.source_event_id != source_event_id:
            continue
        if not entity.has_relationship(ObligationDebtor, debtor_id):
            continue
        if entity.has_relationship(ObligationCreditor, creditor_id):
            return entity
    return None


def create_obligation(
    world: World,
    *,
    kind: str,
    text: str,
    debtor_id: EntityId,
    creditor_id: EntityId,
    source_event_id: str = "",
    created_at_epoch: int = 0,
    due_epoch: int = 0,
) -> Entity | None:
    """Create one explicit obligation between two existing entities."""

    clean_text = " ".join(text.split())
    if (
        kind not in _OBLIGATION_INTENTS
        or not clean_text
        or not world.has_entity(debtor_id)
        or not world.has_entity(creditor_id)
    ):
        return None
    if source_event_id and obligation_for_source(world, source_event_id, debtor_id, creditor_id):
        return None
    debtor_name = entity_name(world.get_entity(debtor_id), "someone")
    creditor_name = entity_name(world.get_entity(creditor_id), "someone")
    obligation = spawn_entity(
        world,
        [
            IdentityComponent(
                name=f"{kind.title()} from {debtor_name} to {creditor_name}",
                kind="obligation",
            ),
            ObligationComponent(
                kind=kind,
                text=clean_text,
                source_event_id=source_event_id,
                created_at_epoch=created_at_epoch,
                due_epoch=due_epoch,
            ),
        ],
    )
    obligation.add_relationship(ObligationDebtor(), debtor_id)
    obligation.add_relationship(ObligationCreditor(), creditor_id)
    return obligation


def obligations_for(
    world: World, character_id: EntityId, *, include_resolved: bool = False
) -> list[tuple[Entity, ObligationComponent]]:
    """Return obligations involving ``character_id``, newest first."""

    if not world.has_entity(character_id):
        return []
    obligations = []
    for entity in world.query().with_all([ObligationComponent]).execute_entities():
        component = entity.get_component(ObligationComponent)
        if not include_resolved and component.status != "open":
            continue
        if entity.has_relationship(ObligationDebtor, character_id) or entity.has_relationship(
            ObligationCreditor, character_id
        ):
            obligations.append((entity, component))
    return sorted(
        obligations,
        key=lambda item: (item[1].created_at_epoch, item[0].id),
        reverse=True,
    )


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


class ObligationReactor:
    """Projects promise/request/offer/threat speech into explicit obligation state."""

    def __init__(self, world: World) -> None:
        self.world = world

    def subscribe(self, bus) -> None:
        bus.subscribe(SpeechSaidEvent, self._on_speech)
        bus.subscribe(SpeechToldEvent, self._on_speech)

    def _on_speech(self, event: SpeechSaidEvent | SpeechToldEvent) -> None:
        intent = event.final_interpretation or "neutral"
        if intent not in _OBLIGATION_INTENTS:
            return
        speaker_id = parse_entity_id(event.actor_id) if event.actor_id else None
        if speaker_id is None or not self.world.has_entity(speaker_id):
            return
        for raw_target_id in event.target_ids:
            target_id = parse_entity_id(raw_target_id)
            if target_id is None or target_id == speaker_id or not self.world.has_entity(target_id):
                continue
            if intent == "request":
                debtor_id, creditor_id = target_id, speaker_id
            else:
                debtor_id, creditor_id = speaker_id, target_id
            create_obligation(
                self.world,
                kind=intent,
                text=event.text,
                debtor_id=debtor_id,
                creditor_id=creditor_id,
                source_event_id=event.event_id,
                created_at_epoch=event.world_epoch,
            )


class ObligationResolvedEvent(DomainEvent):
    obligation_id: str
    status: str
    debtor_id: str
    creditor_id: str
    note: str = ""


class ResolveObligationHandler:
    command_type = "resolve-obligation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        obligation_id = parse_entity_id(command.payload.get("obligation_id"))
        if actor_id is None or obligation_id is None:
            return rejected("invalid character or obligation id")
        if not ctx.world.has_entity(obligation_id):
            return rejected("obligation does not exist")
        obligation_entity = ctx.entity(obligation_id)
        if not obligation_entity.has_component(ObligationComponent):
            return rejected("target is not an obligation")
        debtor_id, creditor_id = _obligation_parties(obligation_entity)
        if actor_id not in {debtor_id, creditor_id}:
            return rejected("character is not party to obligation")
        status = str(command.payload.get("status", "")).strip().lower()
        if status not in _OBLIGATION_RESOLUTIONS:
            return rejected("invalid obligation status")
        obligation = obligation_entity.get_component(ObligationComponent)
        if obligation.status != "open":
            return rejected("obligation is already resolved")
        note = str(command.payload.get("note", "")).strip()
        updated = ObligationComponent(
            kind=obligation.kind,
            text=obligation.text,
            status=status,
            source_event_id=obligation.source_event_id,
            created_at_epoch=obligation.created_at_epoch,
            due_epoch=obligation.due_epoch,
            resolved_at_epoch=ctx.epoch,
            resolution_note=note,
        )
        replace_component(obligation_entity, updated)
        _apply_obligation_resolution(ctx.world, debtor_id, creditor_id, status)
        return ok(
            ObligationResolvedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(actor_id),
                    target_ids=(str(obligation_id), str(debtor_id), str(creditor_id)),
                    obligation_id=str(obligation_id),
                    status=status,
                    debtor_id=str(debtor_id),
                    creditor_id=str(creditor_id),
                    note=note,
                )
            )
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
    # get_relationships only yields live targets: world.remove() cascades incoming edges, so a
    # dangling target_id can't appear here.
    for bond, target_id in character.get_relationships(SocialBond):
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


def obligation_fragments(world: World, character: Entity) -> list[str]:
    """Prompt lines for open obligations involving a character."""

    lines = []
    for entity, component in obligations_for(world, character.id)[:_OBLIGATION_PROMPT_LIMIT]:
        debtor_id, creditor_id = _obligation_parties(entity)
        if character.id == debtor_id:
            other = entity_name(world.get_entity(creditor_id), "someone")
            lines.append(
                f"You owe {other}: {component.text} "
                f"[obligation:{entity.id} kind:{component.kind}]"
            )
        else:
            # obligations_for only returns obligations the character is party to, so if it is
            # not the debtor it is necessarily the creditor.
            other = entity_name(world.get_entity(debtor_id), "someone")
            lines.append(
                f"{other} owes you: {component.text} "
                f"[obligation:{entity.id} kind:{component.kind}]"
            )
    return sorted(lines)


def _obligation_parties(entity: Entity) -> tuple[EntityId, EntityId]:
    debtor = entity.get_relationships(ObligationDebtor)[0][1]
    creditor = entity.get_relationships(ObligationCreditor)[0][1]
    return debtor, creditor


def _apply_obligation_resolution(
    world: World, debtor_id: EntityId, creditor_id: EntityId, status: str
) -> None:
    # Both parties are resolved from a live obligation's edges, so they exist here.
    if status == "fulfilled":
        adjust_bond(world, creditor_id, debtor_id, {"trust": 0.1, "affinity": 0.05})
    elif status == "failed":
        adjust_bond(world, creditor_id, debtor_id, {"trust": -0.15, "resentment": 0.08})


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
    ObligationReactor(actor.world).subscribe(actor.bus)


__all__ = [
    "GossipClaimComponent",
    "GossipReactor",
    "KnowsGossip",
    "ObligationComponent",
    "ObligationCreditor",
    "ObligationDebtor",
    "ObligationReactor",
    "ObligationResolvedEvent",
    "RelationshipReactor",
    "ResolveObligationHandler",
    "SocialBond",
    "SpeechInterpretation",
    "adjust_bond",
    "bond_between",
    "create_gossip_claim",
    "create_obligation",
    "gossip_fragments",
    "install_social",
    "interpret_speech_for_listener",
    "known_gossip",
    "learn_gossip",
    "obligation_for_source",
    "obligation_fragments",
    "obligations_for",
    "relationship_fragments",
]
