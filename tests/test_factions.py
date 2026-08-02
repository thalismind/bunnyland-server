"""Tests for shared faction membership, visibility, and directed stance."""

from __future__ import annotations

from conftest import build_scenario, execute_handler

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.handlers import HandlerContext
from bunnyland.foundation.factions.mechanics import (
    FactionComponent,
    FactionDisposition,
    FactionDispositionStance,
    FactionStance,
    JoinFactionHandler,
    LeaveFactionHandler,
    MemberOfFaction,
    faction_fragments,
    resolve_actor_stance,
    resolve_faction_stance,
)
from bunnyland.foundation.factions.plugin import bunnyland_plugins as faction_plugins


def _faction(world, name: str, *, secret: bool = False):
    return spawn_entity(
        world,
        [IdentityComponent(name=name, kind="faction"), FactionComponent(name=name, secret=secret)],
    )


def _character_in_room(scenario, name: str):
    character = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="character"), CharacterComponent(species="animal")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), character.id
    )
    return character


def _command(scenario, command_type: str, faction_id: str):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"faction_id": faction_id},
    )


def test_affliction_factions_resolve_hostile_with_precedence_over_shared_membership():
    scenario = build_scenario()
    world = scenario.actor.world
    afflicted = _faction(world, "Moon Afflicted", secret=True)
    hunters = _faction(world, "Lantern Hunters")
    neighbors = _faction(world, "Burrow Neighbors")
    afflicted.add_relationship(
        FactionDisposition(stance=FactionDispositionStance.HOSTILE), hunters.id
    )

    observer = world.get_entity(scenario.character)
    target = _character_in_room(scenario, "Nightbound Hare")
    observer.add_relationship(MemberOfFaction(), afflicted.id)
    observer.add_relationship(MemberOfFaction(), neighbors.id)
    target.add_relationship(MemberOfFaction(), hunters.id)
    target.add_relationship(MemberOfFaction(), neighbors.id)

    assert resolve_actor_stance(world, observer, target) is FactionStance.HOSTILE


def test_lion_hyena_and_predator_prey_examples_use_directed_dispositions():
    scenario = build_scenario()
    world = scenario.actor.world
    lions = _faction(world, "Lions")
    hyenas = _faction(world, "Hyenas")
    predators = _faction(world, "Predators")
    prey = _faction(world, "Prey")
    lions.add_relationship(FactionDisposition(stance="hostile"), hyenas.id)
    predators.add_relationship(FactionDisposition(stance="hostile"), prey.id)

    lion = world.get_entity(scenario.character)
    lion.add_relationship(MemberOfFaction(), lions.id)
    hyena = _character_in_room(scenario, "Hyena")
    hyena.add_relationship(MemberOfFaction(), hyenas.id)
    gazelle = _character_in_room(scenario, "Gazelle")
    gazelle.add_relationship(MemberOfFaction(), prey.id)
    lion.add_relationship(MemberOfFaction(), predators.id)

    assert resolve_actor_stance(world, lion, hyena) is FactionStance.HOSTILE
    assert resolve_actor_stance(world, lion, gazelle) is FactionStance.HOSTILE
    assert resolve_actor_stance(world, gazelle, lion) is FactionStance.NEUTRAL


def test_shared_and_explicitly_friendly_memberships_resolve_friendly():
    scenario = build_scenario()
    world = scenario.actor.world
    lions = _faction(world, "Lions")
    hyenas = _faction(world, "Hyenas")
    waterhole = _faction(world, "Waterhole Truce")
    lions.add_relationship(FactionDisposition(stance="friendly"), hyenas.id)
    observer = world.get_entity(scenario.character)
    target = _character_in_room(scenario, "Hyena")
    observer.add_relationship(MemberOfFaction(), lions.id)
    target.add_relationship(MemberOfFaction(), hyenas.id)

    assert resolve_actor_stance(world, observer, target) is FactionStance.FRIENDLY

    observer.remove_relationship(MemberOfFaction, lions.id)
    target.remove_relationship(MemberOfFaction, hyenas.id)
    observer.add_relationship(MemberOfFaction(), waterhole.id)
    target.add_relationship(MemberOfFaction(), waterhole.id)
    assert resolve_actor_stance(world, observer, target) is FactionStance.FRIENDLY


def test_faction_pair_with_missing_endpoint_is_neutral():
    scenario = build_scenario()
    world = scenario.actor.world
    existing = _faction(world, "Existing")
    removed = _faction(world, "Removed")
    removed_id = removed.id
    world.remove(removed)

    assert resolve_faction_stance(world, existing.id, removed_id) is FactionStance.NEUTRAL


def test_factions_package_entrypoint_returns_foundation_plugin():
    plugins = faction_plugins()

    assert len(plugins) == 1
    assert plugins[0].id == "bunnyland.factions"


def test_secret_membership_is_private_but_nearby_stance_hides_faction_identity():
    scenario = build_scenario()
    world = scenario.actor.world
    wardens = _faction(world, "Sun Wardens")
    secret = _faction(world, "The Unspoken Court", secret=True)
    wardens.add_relationship(FactionDisposition(stance="hostile"), secret.id)

    viewer = world.get_entity(scenario.character)
    hidden_member = _character_in_room(scenario, "Moth")
    viewer.add_relationship(MemberOfFaction(rank="warden"), wardens.id)
    hidden_member.add_relationship(MemberOfFaction(rank="agent"), secret.id)

    viewer_lines = faction_fragments(world, viewer)
    member_lines = faction_fragments(world, hidden_member)

    assert "Nearby Moth is hostile." in viewer_lines
    assert all("Unspoken Court" not in line for line in viewer_lines)
    assert "You are a agent of The Unspoken Court." in member_lines


def test_public_join_and_leave_reject_secret_factions_without_mutation():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    secret = _faction(world, "The Unspoken Court", secret=True)
    context = HandlerContext(world=world, epoch=17)

    join = execute_handler(
        JoinFactionHandler(), context, _command(scenario, "join-faction", str(secret.id))
    )
    assert not join.ok
    assert join.reason == "secret factions cannot be joined publicly"
    assert not character.has_relationship(MemberOfFaction, secret.id)

    character.add_relationship(MemberOfFaction(rank="agent", since_epoch=3), secret.id)
    leave = execute_handler(
        LeaveFactionHandler(), context, _command(scenario, "leave-faction", str(secret.id))
    )
    assert not leave.ok
    assert leave.reason == "secret factions cannot be left publicly"
    assert character.has_relationship(MemberOfFaction, secret.id)


def test_dragonsim_reexports_the_foundation_faction_contracts():
    from bunnyland.simpacks.dragonsim import mechanics as dragonsim

    assert dragonsim.FactionComponent is FactionComponent
    assert dragonsim.MemberOfFaction is MemberOfFaction
