"""Policy, boundaries, and the allow/deny gate (spec 20).

Sensitive interactions (flirting, romance, PvP, theft, ...) are gated. A tagged action is
allowed only if the world enables the tag (or every participant has opted in) and no
participant has denied it. **Denied always wins** — there is no admin override; an admin can
moderate the world but cannot make a character opt into something it (or its player) refused.

The gate is registered on the world actor as a ``CommandGate``; a classifier maps a command
to ``(tag, participants)``. Untagged commands pass freely. Today the one classifier maps
flirtatious speech to the FLIRTING tag, but the machinery is general.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic.dataclasses import dataclass
from relics import Component, Entity, World

from ..core.commands import SubmittedCommand
from ..core.components import IdentityComponent, WorldClockComponent
from ..core.ecs import parse_entity_id, spawn_entity

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


class BoundaryTag(StrEnum):
    FLIRTING = "flirting"
    ROMANCE = "romance"
    ADULT = "adult"
    PREGNANCY = "pregnancy"
    PVP = "pvp"
    LETHAL_PVP = "lethal_pvp"
    THEFT = "theft"
    PICKPOCKETING = "pickpocketing"


@dataclass(frozen=True)
class WorldPolicyComponent(Component):
    """What the world makes available at all (spec 20.3)."""

    enabled: frozenset[BoundaryTag] = frozenset()
    disabled: frozenset[BoundaryTag] = frozenset()


@dataclass(frozen=True)
class CharacterBoundaryComponent(Component):
    """A character's opt-ins and opt-outs (spec 20.2). Denied always wins."""

    allowed: frozenset[BoundaryTag] = frozenset()
    denied: frozenset[BoundaryTag] = frozenset()


# A classifier maps a command to the boundary it touches and the participants who must
# consent, or None if the command is unrestricted.
Classifier = "Callable[[SubmittedCommand], tuple[BoundaryTag, list[str]] | None]"


def _world_policy(world: World) -> WorldPolicyComponent:
    for entity in world.query().with_all([WorldPolicyComponent]).execute_entities():
        return entity.get_component(WorldPolicyComponent)
    return WorldPolicyComponent()


def _boundary(world: World, raw_id: str) -> tuple[str, CharacterBoundaryComponent | None]:
    entity_id = parse_entity_id(raw_id)
    if entity_id is None or not world.has_entity(entity_id):
        return raw_id, None
    entity = world.get_entity(entity_id)
    name = (
        entity.get_component(IdentityComponent).name
        if entity.has_component(IdentityComponent)
        else raw_id
    )
    boundary = (
        entity.get_component(CharacterBoundaryComponent)
        if entity.has_component(CharacterBoundaryComponent)
        else None
    )
    return name, boundary


def evaluate(
    world: World, tag: BoundaryTag, participants: list[str]
) -> tuple[bool, str | None]:
    """Decide whether a ``tag`` action among ``participants`` is permitted (spec 20.3)."""
    policy = _world_policy(world)
    if tag in policy.disabled:
        return False, f"{tag.value} is disabled in this world"

    named = [_boundary(world, raw) for raw in participants]
    for name, boundary in named:
        if boundary is not None and tag in boundary.denied:
            return False, f"{name} has not consented to {tag.value}"

    world_enables = tag in policy.enabled
    everyone_opted_in = bool(named) and all(
        boundary is not None and tag in boundary.allowed for _name, boundary in named
    )
    if world_enables or everyone_opted_in:
        return True, None
    return False, f"{tag.value} is not enabled here"


def boundary_fragments(world: World, character: Entity) -> list[str]:
    """Stable prompt lines describing applicable world and character boundaries."""

    lines: list[str] = []
    policy = _world_policy(world)
    if policy.enabled:
        enabled = ", ".join(sorted(tag.value for tag in policy.enabled))
        lines.append(f"World boundaries enabled: {enabled}.")
    if policy.disabled:
        disabled = ", ".join(sorted(tag.value for tag in policy.disabled))
        lines.append(f"World boundaries disabled: {disabled}.")
    if character.has_component(CharacterBoundaryComponent):
        boundary = character.get_component(CharacterBoundaryComponent)
        if boundary.allowed:
            allowed = ", ".join(sorted(tag.value for tag in boundary.allowed))
            lines.append(f"Your allowed boundaries: {allowed}.")
        if boundary.denied:
            denied = ", ".join(sorted(tag.value for tag in boundary.denied))
            lines.append(f"Your denied boundaries: {denied}.")
    return lines


def flirt_classifier(command: SubmittedCommand):
    """Flirtatious speech requires the FLIRTING boundary between speaker and target."""
    if command.command_type not in ("say", "tell"):
        return None
    if command.payload.get("intent") != "flirt":
        return None
    participants = [command.character_id]
    target = command.payload.get("target_id")
    if target:
        participants.append(str(target))
    return BoundaryTag.FLIRTING, participants


class PolicyGate:
    """A command gate (spec 20): runs each classifier and denies on the first failed tag."""

    def __init__(self, classifiers) -> None:
        self._classifiers = list(classifiers)

    def __call__(self, world: World, command: SubmittedCommand) -> tuple[bool, str | None]:
        for classify in self._classifiers:
            tagged = classify(command)
            if tagged is None:
                continue
            tag, participants = tagged
            allowed, reason = evaluate(world, tag, participants)
            if not allowed:
                return False, reason
        return True, None


def install_policy(
    actor: WorldActor,
    *,
    enabled: frozenset[BoundaryTag] | None = None,
    disabled: frozenset[BoundaryTag] | None = None,
    classifiers=(flirt_classifier,),
) -> None:
    """Register the policy gate and ensure a world policy exists (kept if already present)."""
    if enabled is None:
        enabled = frozenset({BoundaryTag.FLIRTING})  # a social sandbox allows flirting
    if disabled is None:
        disabled = frozenset()

    if not list(actor.world.query().with_all([WorldPolicyComponent]).execute_entities()):
        clocks = list(actor.world.query().with_all([WorldClockComponent]).execute_entities())
        target = clocks[0] if clocks else spawn_entity(actor.world)
        target.add_component(WorldPolicyComponent(enabled=enabled, disabled=disabled))

    actor.register_gate(PolicyGate(classifiers))


__all__ = [
    "BoundaryTag",
    "CharacterBoundaryComponent",
    "PolicyGate",
    "WorldPolicyComponent",
    "boundary_fragments",
    "evaluate",
    "flirt_classifier",
    "install_policy",
]
