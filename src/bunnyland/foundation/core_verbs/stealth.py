"""Private prompt facts for the shared stealth surface."""

from __future__ import annotations

from relics import Entity, World

from ...core.components import IdentityComponent, StealthComponent
from ...core.edges import DetectedStealth
from ...core.stealth import is_hidden, observer_detects


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


def stealth_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    if is_hidden(character):
        since_epoch = character.get_component(StealthComponent).since_epoch
        lines.append(f"You are hidden (hide attempt {since_epoch}).")
        detected_by = []
        for observer_id, _edge in character.get_incoming_relationships(DetectedStealth):
            observer = world.get_entity(observer_id)
            if observer_detects(world, observer, character):
                detected_by.append(_name(observer))
        if detected_by:
            lines.append(f"Your hiding has been detected by: {', '.join(sorted(detected_by))}.")

    detected: list[str] = []
    for _edge, target_id in character.get_relationships(DetectedStealth):
        target = world.get_entity(target_id)
        if observer_detects(world, character, target):
            detected.append(_name(target))
    if detected:
        lines.append(f"You detect hidden nearby: {', '.join(sorted(detected))}.")
    return lines


__all__ = ["stealth_fragments"]
