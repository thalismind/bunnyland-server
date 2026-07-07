"""Shared helpers for assigning external controllers to characters."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from time import time
from typing import Any
from uuid import uuid4

from relics import Component

from .core.components import CharacterComponent, IdentityComponent, SuspendedComponent
from .core.contracts import ActorContext, EntityLike
from .core.controllers import (
    ClaimedComponent,
    ClaimTimeoutComponent,
)
from .core.ecs import replace_component
from .core.edges import ControlledBy
from .mechanics.lifesim import LifeStageComponent

CHILD_LIFE_STAGES = frozenset({"baby", "infant", "toddler", "child"})
CLIENT_KIND_DISCORD = "discord"
CLIENT_KIND_MCP = "mcp"
CLIENT_KIND_WEB = "web"


class ClaimSecretRegistry:
    """In-memory bearer-secret store for controller claims.

    Claim ids are public ECS metadata. Secrets are process-local and are never
    persisted into the world or exposed through admin snapshots.
    """

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def issue(self, claim_id: str) -> str:
        if claim_id in self._secrets:
            raise ValueError("claim secret already exists")
        secret = secrets.token_urlsafe(32)
        self._secrets[claim_id] = secret
        return secret

    def has_secret(self, claim_id: str) -> bool:
        return claim_id in self._secrets

    def secret(self, claim_id: str) -> str | None:
        return self._secrets.get(claim_id)

    def validate(self, claim_id: str, secret: str | None) -> bool:
        expected = self._secrets.get(claim_id)
        if expected is None or secret is None:
            return False
        return secrets.compare_digest(expected, secret)

    def revoke(self, claim_id: str) -> None:
        self._secrets.pop(claim_id, None)

    def clear(self) -> None:
        self._secrets.clear()


def is_child_character(character: EntityLike) -> bool:
    if not character.has_component(LifeStageComponent):
        return False
    stage = character.get_component(LifeStageComponent).stage
    return stage.lower() in CHILD_LIFE_STAGES


def match_character_by_name(characters: Iterable[EntityLike], character_name: str):
    lowered = character_name.lower()
    character_list = list(characters)
    exact = [
        character
        for character in character_list
        if character.get_component(IdentityComponent).name.lower() == lowered
    ]
    if exact:
        return exact[0]
    prefix = [
        character
        for character in character_list
        if character.get_component(IdentityComponent).name.lower().startswith(lowered)
    ]
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        names = ", ".join(character.get_component(IdentityComponent).name for character in prefix)
        raise RuntimeError(f"multiple characters match {character_name!r}: {names}")
    return None


def claimable_characters(
    actor: ActorContext,
    characters: Iterable[EntityLike],
    *,
    allow_child_claims: bool,
):
    claimable = [
        character
        for character in characters
        if (
            character.has_component(SuspendedComponent)
            or not character_has_claim(actor, character)
        )
        and (allow_child_claims or not is_child_character(character))
    ]
    return sorted(claimable, key=lambda character: not character.has_component(SuspendedComponent))


def controller_claim(controller: EntityLike) -> ClaimedComponent | None:
    if controller.has_component(ClaimedComponent):
        return controller.get_component(ClaimedComponent)
    return None


def current_controller(
    actor: ActorContext,
    character: EntityLike,
) -> tuple[EntityLike, ControlledBy] | None:
    for edge, controller_id in character.get_relationships(ControlledBy):
        if actor.world.has_entity(controller_id):
            return actor.world.get_entity(controller_id), edge
    return None


def character_has_claim(actor: ActorContext, character: EntityLike) -> bool:
    for _edge, controller_id in character.get_relationships(ControlledBy):
        if actor.world.has_entity(controller_id):
            controller = actor.world.get_entity(controller_id)
            if controller.has_component(ClaimedComponent):
                return True
    return False


def claim_matches(claim: ClaimedComponent, client_kind: str, client_id: str) -> bool:
    return (
        claim.client_kind == client_kind.strip().lower()
        and claim.client_id == client_id.strip()
    )


def claim_client_matches(claim: ClaimedComponent, client_id: str) -> bool:
    return claim.client_id == client_id.strip()


def ensure_claim_secret(
    registry: ClaimSecretRegistry,
    claim: ClaimedComponent,
    *,
    claim_id: str | None = None,
    claim_secret: str | None = None,
) -> None:
    if claim_id is not None and claim_id.strip() and claim_id.strip() != claim.claim_id:
        raise PermissionError("invalid claim id")
    if not registry.validate(claim.claim_id, claim_secret):
        raise PermissionError("invalid claim secret")


def add_claim(
    controller: EntityLike,
    *,
    client_kind: str,
    client_id: str,
    character_id: str,
    label: str = "",
    claim_id: str | None = None,
    now_unix: int | None = None,
) -> ClaimedComponent:
    claim = ClaimedComponent(
        claim_id=claim_id or uuid4().hex,
        client_kind=client_kind.strip().lower(),
        client_id=client_id.strip(),
        character_id=character_id,
        label=label.strip(),
        claimed_at_unix=now_unix if now_unix is not None else int(time()),
    )
    if controller.has_component(ClaimedComponent):
        replace_component(controller, claim)
    else:
        controller.add_component(claim)
    return claim


def transfer_claim(
    old_controller: EntityLike,
    new_controller: EntityLike,
) -> ClaimedComponent | None:
    if old_controller.id == new_controller.id:
        return controller_claim(old_controller)
    claim = controller_claim(old_controller)
    if claim is None:
        return None
    existing = controller_claim(new_controller)
    if existing is not None and existing.claim_id != claim.claim_id:
        raise RuntimeError("target controller is already claimed")
    if new_controller.has_component(ClaimedComponent):
        replace_component(new_controller, claim)
    else:
        new_controller.add_component(claim)
    old_controller.remove_component(ClaimedComponent)
    if old_controller.has_component(ClaimTimeoutComponent):
        timeout = old_controller.get_component(ClaimTimeoutComponent)
        if new_controller.has_component(ClaimTimeoutComponent):
            replace_component(new_controller, timeout)
        else:
            new_controller.add_component(timeout)
        old_controller.remove_component(ClaimTimeoutComponent)
    return claim


def remove_claim(
    controller: EntityLike,
    registry: ClaimSecretRegistry | None = None,
) -> ClaimedComponent | None:
    claim = controller_claim(controller)
    if claim is None:
        return None
    if registry is not None:
        registry.revoke(claim.claim_id)
    controller.remove_component(ClaimedComponent)
    return claim


def claimed_character_for(
    actor: ActorContext,
    *,
    client_id: str,
) -> tuple[Any, Any, ControlledBy, ClaimedComponent] | None:
    parsed_client = client_id.strip()
    characters = actor.world.query().with_all([CharacterComponent]).execute_entities()
    for character in characters:
        found = current_controller(actor, character)
        if found is None:
            continue
        controller, edge = found
        claim = controller_claim(controller)
        if claim is not None and claim_client_matches(claim, parsed_client):
            return character, controller, edge, claim
    return None


def normalize_claimed_controllers_without_secrets(
    actor: ActorContext,
    registry: ClaimSecretRegistry,
) -> None:
    """Drop persisted public claims that no longer have in-memory secret state."""

    controllers = actor.world.query().with_all([ClaimedComponent]).execute_entities()
    for controller in list(controllers):
        claim = controller.get_component(ClaimedComponent)
        if claim.client_kind == CLIENT_KIND_DISCORD:
            continue
        if registry.has_secret(claim.claim_id):
            continue
        controller.remove_component(ClaimedComponent)


def matching_controller(
    actor: ActorContext,
    controller_component_type: type[Component],
    matches_controller: Callable[[Component], bool],
):
    controllers = actor.world.query().with_all([controller_component_type])
    for controller in sorted(controllers.execute_entities(), key=lambda item: str(item.id)):
        if matches_controller(controller.get_component(controller_component_type)):
            return controller
    return None


def controlled_character(
    actor: ActorContext,
    controller_component_type: type[Component],
    matches_controller: Callable[[Component], bool],
):
    controller = matching_controller(actor, controller_component_type, matches_controller)
    if controller is not None:
        controller_id = controller.id
        characters = actor.world.query().with_all([CharacterComponent]).execute_entities()
        for character in characters:
            for edge, target in character.get_relationships(ControlledBy):
                if target == controller_id:
                    return character.id, controller_id, edge.generation
    return None


__all__ = [
    "CHILD_LIFE_STAGES",
    "CLIENT_KIND_DISCORD",
    "CLIENT_KIND_MCP",
    "CLIENT_KIND_WEB",
    "ClaimSecretRegistry",
    "add_claim",
    "claim_client_matches",
    "claim_matches",
    "claimable_characters",
    "claimed_character_for",
    "controller_claim",
    "controlled_character",
    "current_controller",
    "ensure_claim_secret",
    "is_child_character",
    "match_character_by_name",
    "matching_controller",
    "normalize_claimed_controllers_without_secrets",
    "remove_claim",
    "transfer_claim",
]
