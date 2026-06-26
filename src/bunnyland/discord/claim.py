"""Helpers for assigning Discord users to in-world characters."""

from __future__ import annotations

import time

from ..claims import (
    CLIENT_KIND_DISCORD,
    ClaimSecretRegistry,
    add_claim,
    claim_client_matches,
    claimable_characters,
    claimed_character_for,
    controller_claim,
    current_controller,
    ensure_claim_secret,
    is_child_character,
    match_character_by_name,
    matching_controller,
    remove_claim,
    transfer_claim,
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
from ..core.claim_timeout import (
    apply_claim_timeout_settings,
    normalize_claim_fallback,
    record_claim_activity,
)
from ..core.world_actor import WorldActor

_DEFAULT_CLAIM_SECRETS = ClaimSecretRegistry()


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


def _claimable_characters(actor: WorldActor, characters, *, allow_child_claims: bool):
    return claimable_characters(actor, characters, allow_child_claims=allow_child_claims)


def _discord_controller_for(actor: WorldActor, discord_user_id: int, default_channel_id: int):
    return matching_controller(
        actor,
        DiscordControllerComponent,
        lambda controller: (
            controller.discord_user_id == discord_user_id
            and controller.default_channel_id == default_channel_id
        ),
    )


def _discord_client_id(discord_user_id: int) -> str:
    return str(discord_user_id)


def assign_discord_controller(
    actor: WorldActor,
    *,
    claim_secrets: ClaimSecretRegistry | None = None,
    discord_user_id: int,
    default_channel_id: int = 0,
    claim_id: str | None = None,
    claim_secret: str | None = None,
    character_name: str | None = None,
    allow_child_claims: bool = False,
    fallback_controller: str | None = None,
    timeout_seconds: int | None = None,
    llm_model: str | None = None,
    llm_provider: str | None = None,
) -> str:
    """Assign a Discord controller to a named character, or the first claimable one."""

    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    client_id = _discord_client_id(discord_user_id)
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
        suspended = _claimable_characters(
            actor,
            characters,
            allow_child_claims=allow_child_claims,
        )
        if not suspended:
            raise RuntimeError("no suspended claimable character exists in the world")
        character = suspended[0]

    active = current_controller(actor, character)
    active_controller = active[0] if active is not None else None
    active_claim = controller_claim(active_controller) if active_controller is not None else None
    issued_claim_id = None
    if active_claim is not None:
        if not claim_client_matches(active_claim, client_id):
            raise RuntimeError("character is already claimed")
        if claim_id is not None or claim_secret is not None:
            try:
                ensure_claim_secret(
                    claim_secrets,
                    active_claim,
                    claim_id=claim_id,
                    claim_secret=claim_secret,
                )
            except PermissionError as exc:
                raise RuntimeError(str(exc)) from exc
        issued_claim_id = active_claim.claim_id
        claim_secret = claim_secrets.secret(active_claim.claim_id)

    controller = _discord_controller_for(actor, discord_user_id, default_channel_id)
    if controller is not None:
        existing_claim = controller_claim(controller)
        if existing_claim is not None and existing_claim.character_id != str(character.id):
            controller = None
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
                if controller_claim(controller) is None:
                    claim = add_claim(
                        controller,
                        client_kind=CLIENT_KIND_DISCORD,
                        client_id=client_id,
                        character_id=str(character.id),
                        claim_id=issued_claim_id,
                    )
                    claim_secrets.issue(claim.claim_id)
                elif not claim_secrets.has_secret(controller_claim(controller).claim_id):
                    claim_secrets.issue(controller_claim(controller).claim_id)
                return character.get_component(IdentityComponent).name
    if active_claim is not None and active_controller is not None:
        transfer_claim(active_controller, controller)
    claim = add_claim(
        controller,
        client_kind=CLIENT_KIND_DISCORD,
        client_id=client_id,
        character_id=str(character.id),
        claim_id=issued_claim_id,
        now_unix=active_claim.claimed_at_unix if active_claim is not None else None,
    )
    if claim_secret is None or not claim_secrets.has_secret(claim.claim_id):
        claim_secret = claim_secrets.issue(claim.claim_id)
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
    """Find the character actively controlled by a claimed Discord controller, if any."""

    client_id = _discord_client_id(discord_user_id)
    characters = actor.world.query().with_all([CharacterComponent]).execute_entities()
    for character in characters:
        found = current_controller(actor, character)
        if found is None:
            continue
        controller, edge = found
        if not controller.has_component(DiscordControllerComponent):
            continue
        discord = controller.get_component(DiscordControllerComponent)
        claim = controller_claim(controller)
        if (
            discord.discord_user_id == discord_user_id
            and claim is not None
            and claim_client_matches(claim, client_id)
        ):
            return character.id, controller.id, edge.generation
    return None


def discord_claimed_character(actor: WorldActor, discord_user_id: int):
    """Find any live claim owned by a Discord user, including idle fallback controllers."""

    return claimed_character_for(actor, client_id=_discord_client_id(discord_user_id))


def resume_discord_claim(
    actor: WorldActor,
    *,
    discord_user_id: int,
    default_channel_id: int = 0,
) -> tuple[object, object, int] | None:
    """Resume a Discord user's claimed character under a Discord controller."""

    found = discord_claimed_character(actor, discord_user_id)
    if found is None:
        return None
    character, active_controller, edge, claim = found
    client_id = _discord_client_id(discord_user_id)
    if active_controller.has_component(DiscordControllerComponent):
        discord = active_controller.get_component(DiscordControllerComponent)
        if discord.discord_user_id == discord_user_id:
            record_claim_activity(active_controller, now_unix=int(time.time()))
            return character, active_controller.id, edge.generation

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
    existing_claim = controller_claim(controller)
    if existing_claim is not None and existing_claim.claim_id != claim.claim_id:
        controller = spawn_entity(
            actor.world,
            [
                DiscordControllerComponent(
                    discord_user_id=discord_user_id,
                    default_channel_id=default_channel_id,
                )
            ],
        )
    transfer_claim(active_controller, controller)
    add_claim(
        controller,
        client_kind=CLIENT_KIND_DISCORD,
        client_id=client_id,
        character_id=claim.character_id,
        label=claim.label,
        claim_id=claim.claim_id,
        now_unix=claim.claimed_at_unix,
    )
    generation = actor.assign_controller(character.id, controller.id)
    if character.has_component(SuspendedComponent):
        character.remove_component(SuspendedComponent)
    record_claim_activity(controller, now_unix=int(time.time()))
    return character, controller.id, generation


def _controlled_character(actor: WorldActor, discord_user_id: int):
    found = resume_discord_claim(actor, discord_user_id=discord_user_id)
    if found is None:
        raise RuntimeError("You are not controlling a character yet.")
    character, controller_id, _generation = found
    return character, controller_id


def _claimed_character(actor: WorldActor, discord_user_id: int):
    found = discord_claimed_character(actor, discord_user_id)
    if found is None:
        raise RuntimeError("You do not have a character claim.")
    character, controller, _edge, _claim = found
    return character, controller


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

    character, controller = _claimed_character(actor, discord_user_id)
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


def release_discord_claim(
    actor: WorldActor,
    *,
    claim_secrets: ClaimSecretRegistry | None = None,
    discord_user_id: int,
) -> str:
    """Release a Discord user's claim without changing the character's controller."""

    claim_secrets = claim_secrets or _DEFAULT_CLAIM_SECRETS
    character, controller = _claimed_character(actor, discord_user_id)
    remove_claim(controller, claim_secrets)
    return character.get_component(IdentityComponent).name


def suspend_discord_character(
    actor: WorldActor,
    *,
    discord_user_id: int,
    reason: str = "player suspended",
) -> str:
    """Suspend a Discord user's current character so it can be claimed again later."""

    character, old_controller_id = _controlled_character(actor, discord_user_id)
    old_controller = actor.world.get_entity(old_controller_id)
    controller = spawn_entity(actor.world, [SuspendedControllerComponent(reason=reason)])
    transfer_claim(old_controller, controller)
    actor.suspend(character.id, controller.id, reason=reason)
    _retire_discord_controller(actor, old_controller_id)
    return character.get_component(IdentityComponent).name


__all__ = [
    "assign_discord_controller",
    "discord_controlled_character",
    "list_character_names",
    "list_character_statuses",
    "discord_claimed_character",
    "release_discord_claim",
    "render_character_list",
    "resume_discord_claim",
    "set_discord_claim_fallback",
    "suspend_discord_character",
]
