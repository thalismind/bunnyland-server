"""Helpers for assigning Discord users to in-world characters."""

from __future__ import annotations

import os
import time

from ..claims import (
    claimable_characters,
    controlled_character,
    is_child_character,
    match_character_by_name,
    matching_controller,
)
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
from ..core.claim_timeout import apply_claim_timeout_settings, normalize_claim_fallback
from ..core.world_actor import WorldActor
from ..llm_agents import DEFAULT_MODEL


def list_character_names(actor: WorldActor) -> list[str]:
    """Return public character names in the current world."""

    characters = actor.world.query().with_all([CharacterComponent, IdentityComponent])
    return [
        character.get_component(IdentityComponent).name
        for character in characters.execute_entities()
    ]


def _active_controller_kind(actor: WorldActor, character) -> str:
    # Relics cascades inbound relationship removal when an entity is despawned, so every
    # ControlledBy target here is guaranteed to still exist.
    for _edge, controller_id in character.get_relationships(ControlledBy):
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
    return match_character_by_name(characters, character_name)


def _is_child_character(character) -> bool:
    return is_child_character(character)


def _claimable_characters(characters, *, allow_child_claims: bool):
    return claimable_characters(characters, allow_child_claims=allow_child_claims)


def _discord_controller_for(actor: WorldActor, discord_user_id: int, default_channel_id: int):
    return matching_controller(
        actor,
        DiscordControllerComponent,
        lambda controller: (
            controller.discord_user_id == discord_user_id
            and controller.default_channel_id == default_channel_id
        ),
    )


def assign_discord_controller(
    actor: WorldActor,
    *,
    discord_user_id: int,
    default_channel_id: int = 0,
    character_name: str | None = None,
    allow_child_claims: bool = False,
    fallback_controller: str | None = None,
    timeout_seconds: int | None = None,
    llm_model: str | None = None,
    llm_provider: str | None = None,
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
                apply_claim_timeout_settings(
                    controller,
                    now_unix=int(time.time()),
                    fallback_controller=fallback_controller,
                    llm_model=llm_model,
                    llm_provider=llm_provider,
                    timeout_seconds=timeout_seconds,
                    reset_activity=True,
                )
                return character.get_component(IdentityComponent).name
    apply_claim_timeout_settings(
        controller,
        now_unix=int(time.time()),
        fallback_controller=fallback_controller,
        llm_model=llm_model,
        llm_provider=llm_provider,
        timeout_seconds=timeout_seconds,
        reset_activity=True,
    )
    actor.assign_controller(character.id, controller.id)
    if character.has_component(SuspendedComponent):
        character.remove_component(SuspendedComponent)
    return character.get_component(IdentityComponent).name


def discord_controlled_character(actor: WorldActor, discord_user_id: int):
    """Find the character controlled by a Discord user, if any."""

    return controlled_character(
        actor,
        DiscordControllerComponent,
        lambda controller: controller.discord_user_id == discord_user_id,
    )


def _controlled_character(actor: WorldActor, discord_user_id: int):
    found = discord_controlled_character(actor, discord_user_id)
    if found is None:
        raise RuntimeError("You are not controlling a character yet.")
    character_id, controller_id, _generation = found
    return actor.world.get_entity(character_id), controller_id


def set_discord_claim_fallback(
    actor: WorldActor,
    *,
    discord_user_id: int,
    fallback_controller: str,
    timeout_seconds: int | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> tuple[str, str]:
    """Update fallback preferences for a Discord user's current character claim."""

    character, controller_id = _controlled_character(actor, discord_user_id)
    controller = actor.world.get_entity(controller_id)
    fallback = normalize_claim_fallback(fallback_controller)
    apply_claim_timeout_settings(
        controller,
        now_unix=int(time.time()),
        fallback_controller=fallback,
        timeout_seconds=timeout_seconds,
        llm_model=model,
        llm_provider=provider,
        reset_activity=False,
    )
    return character.get_component(IdentityComponent).name, fallback


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
    "set_discord_claim_fallback",
    "suspend_discord_character",
]
