"""Helpers for assigning Discord users to in-world characters."""

from __future__ import annotations

import os

from ..core import (
    CharacterComponent,
    ControlledBy,
    DiscordControllerComponent,
    IdentityComponent,
    LLMControllerComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
    spawn_entity,
)
from ..core.world_actor import WorldActor
from ..llm_agents import DEFAULT_MODEL
from ..mechanics.lifesim import LifeStageComponent

CHILD_LIFE_STAGES = frozenset({"baby", "infant", "toddler", "child"})


def list_character_names(actor: WorldActor) -> list[str]:
    """Return public character names in the current world."""

    characters = actor.world.query().with_all([CharacterComponent, IdentityComponent])
    return [
        character.get_component(IdentityComponent).name
        for character in characters.execute_entities()
    ]


def _active_controller_kind(actor: WorldActor, character) -> str:
    for _edge, controller_id in character.get_relationships(ControlledBy):
        if not actor.world.has_entity(controller_id):
            continue
        controller = actor.world.get_entity(controller_id)
        if controller.has_component(DiscordControllerComponent):
            return "Discord controller"
        if controller.has_component(LLMControllerComponent):
            return "LLM controller"
        if controller.has_component(WebControllerComponent):
            return "player"
        if controller.has_component(SuspendedControllerComponent):
            return "suspended"
    return "free"


def list_character_statuses(actor: WorldActor) -> list[tuple[str, str]]:
    """Return public character names with their player-facing controller status."""

    characters = actor.world.query().with_all([CharacterComponent, IdentityComponent])
    return [
        (
            character.get_component(IdentityComponent).name,
            _active_controller_kind(actor, character),
        )
        for character in characters.execute_entities()
    ]


def render_character_list(actor: WorldActor) -> str:
    """Render the Discord ``!characters`` response."""

    statuses = list_character_statuses(actor)
    if not statuses:
        return "There are no characters in this world."
    lines = ["Characters:"]
    lines.extend(f"- {name} - {status}" for name, status in statuses)
    return "\n".join(lines)


def _match_character(characters, character_name: str):
    lowered = character_name.lower()
    exact = [
        character
        for character in characters
        if character.get_component(IdentityComponent).name.lower() == lowered
    ]
    if exact:
        return exact[0]
    prefix = [
        character
        for character in characters
        if character.get_component(IdentityComponent).name.lower().startswith(lowered)
    ]
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        names = ", ".join(character.get_component(IdentityComponent).name for character in prefix)
        raise RuntimeError(f"multiple characters match {character_name!r}: {names}")
    return None


def _is_child_character(character) -> bool:
    if not character.has_component(LifeStageComponent):
        return False
    stage = character.get_component(LifeStageComponent).stage
    return stage.lower() in CHILD_LIFE_STAGES


def _claimable_characters(characters, *, allow_child_claims: bool):
    return [
        character
        for character in characters
        if character.has_component(SuspendedComponent)
        and (allow_child_claims or not _is_child_character(character))
    ]


def _discord_controller_for(actor: WorldActor, discord_user_id: int, default_channel_id: int):
    controllers = actor.world.query().with_all([DiscordControllerComponent])
    for entity in sorted(controllers.execute_entities(), key=lambda item: str(item.id)):
        controller = entity.get_component(DiscordControllerComponent)
        if (
            controller.discord_user_id == discord_user_id
            and controller.default_channel_id == default_channel_id
        ):
            return entity
    return None


def assign_discord_controller(
    actor: WorldActor,
    *,
    discord_user_id: int,
    default_channel_id: int = 0,
    character_name: str | None = None,
    allow_child_claims: bool = False,
) -> str:
    """Assign a Discord controller to a named character, or the first claimable one."""

    characters = list(
        actor.world.query().with_all([CharacterComponent, IdentityComponent]).execute_entities()
    )
    if character_name:
        character = _match_character(characters, character_name)
        if character is None:
            names = ", ".join(list_character_names(actor))
            raise RuntimeError(
                f"no character named {character_name!r} exists in the world. "
                f"Available characters: {names}"
            )
        if _is_child_character(character) and not allow_child_claims:
            name = character.get_component(IdentityComponent).name
            raise RuntimeError(
                f"{name} is a child character and cannot be claimed on this server"
            )
    else:
        suspended = _claimable_characters(characters, allow_child_claims=allow_child_claims)
        if not suspended:
            raise RuntimeError("no suspended claimable character exists in the world")
        character = suspended[0]

    controller = _discord_controller_for(actor, discord_user_id, default_channel_id)
    if controller is None:
        controller = spawn_entity(
            actor.world,
            [
                DiscordControllerComponent(
                    discord_user_id=discord_user_id,
                    default_channel_id=default_channel_id,
                )
            ],
        )
    else:
        for _edge, controller_id in character.get_relationships(ControlledBy):
            if controller_id == controller.id:
                return character.get_component(IdentityComponent).name
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


def _controlled_character(actor: WorldActor, discord_user_id: int):
    found = discord_controlled_character(actor, discord_user_id)
    if found is None:
        raise RuntimeError("You are not controlling a character yet.")
    character_id, controller_id, _generation = found
    return actor.world.get_entity(character_id), controller_id


def _retire_discord_controller(actor: WorldActor, controller_id) -> None:
    controller = actor.world.get_entity(controller_id)
    if controller.has_component(DiscordControllerComponent):
        controller.remove_component(DiscordControllerComponent)


def release_discord_character_to_llm(
    actor: WorldActor,
    *,
    discord_user_id: int,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """Release a Discord user's current character back to an LLM controller."""

    character, old_controller_id = _controlled_character(actor, discord_user_id)
    controller = spawn_entity(
        actor.world,
        [
            LLMControllerComponent(
                profile_name="default",
                model=model or os.environ.get("BUNNYLAND_CHARACTER_MODEL", DEFAULT_MODEL),
                provider=provider or os.environ.get("BUNNYLAND_LLM_PROVIDER", "ollama"),
            )
        ],
    )
    actor.assign_controller(character.id, controller.id)
    _retire_discord_controller(actor, old_controller_id)
    if character.has_component(SuspendedComponent):
        character.remove_component(SuspendedComponent)
    return character.get_component(IdentityComponent).name


def suspend_discord_character(
    actor: WorldActor,
    *,
    discord_user_id: int,
    reason: str = "player suspended",
) -> str:
    """Suspend a Discord user's current character so it can be claimed again later."""

    character, old_controller_id = _controlled_character(actor, discord_user_id)
    controller = spawn_entity(actor.world, [SuspendedControllerComponent(reason=reason)])
    actor.suspend(character.id, controller.id, reason=reason)
    _retire_discord_controller(actor, old_controller_id)
    return character.get_component(IdentityComponent).name


__all__ = [
    "assign_discord_controller",
    "discord_controlled_character",
    "list_character_names",
    "list_character_statuses",
    "release_discord_character_to_llm",
    "render_character_list",
    "suspend_discord_character",
]
