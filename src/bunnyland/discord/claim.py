"""Helpers for assigning Discord users to in-world characters."""

from __future__ import annotations

from ..core import (
    CharacterComponent,
    ControlledBy,
    DiscordControllerComponent,
    IdentityComponent,
    SuspendedComponent,
    spawn_entity,
)
from ..core.world_actor import WorldActor


def assign_discord_controller(
    actor: WorldActor,
    *,
    discord_user_id: int,
    default_channel_id: int = 0,
    character_name: str | None = None,
) -> str:
    """Assign a Discord controller to a named character, or the first claimable one."""

    characters = list(
        actor.world.query().with_all([CharacterComponent, IdentityComponent]).execute_entities()
    )
    if character_name:
        lowered = character_name.lower()
        matches = [
            character
            for character in characters
            if character.get_component(IdentityComponent).name.lower() == lowered
        ]
        if not matches:
            raise RuntimeError(f"no character named {character_name!r} exists in the world")
        character = matches[0]
    else:
        suspended = [
            character for character in characters if character.has_component(SuspendedComponent)
        ]
        if not suspended:
            raise RuntimeError("no suspended claimable character exists in the world")
        character = suspended[0]

    controller = spawn_entity(
        actor.world,
        [
            DiscordControllerComponent(
                discord_user_id=discord_user_id,
                default_channel_id=default_channel_id,
            )
        ],
    )
    actor.assign_controller(character.id, controller.id)
    if character.has_component(SuspendedComponent):
        character.remove_component(SuspendedComponent)
    return character.get_component(IdentityComponent).name


def discord_controlled_character(actor: WorldActor, discord_user_id: int):
    """Find the character controlled by a Discord user, if any."""

    controllers = actor.world.query().with_all([DiscordControllerComponent]).execute_entities()
    for entity in controllers:
        if entity.get_component(DiscordControllerComponent).discord_user_id != discord_user_id:
            continue
        controller_id = entity.id
        for character in actor.world.query().with_all([]).execute_entities():
            for edge, target in character.get_relationships(ControlledBy):
                if target == controller_id:
                    return character.id, controller_id, edge.generation
    return None


__all__ = ["assign_discord_controller", "discord_controlled_character"]
