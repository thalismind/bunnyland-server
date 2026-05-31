"""Helpers for assigning Discord users to in-world characters."""

from __future__ import annotations

from ..core import (
    CharacterComponent,
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


__all__ = ["assign_discord_controller"]
