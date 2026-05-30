"""Tests for barbarian-sim PvP, combat, and roleplay."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DownedComponent,
    HealthComponent,
    IdentityComponent,
    Lane,
    PortableComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import (
    CharacterAttackedEvent,
    CharacterDefendedEvent,
    CombatChallengeEvent,
    CommandRejectedEvent,
    FortificationBuiltEvent,
    RaidStartedEvent,
)
from bunnyland.mechanics.barbariansim import (
    ArmorComponent,
    AttackHandler,
    ChallengeHandler,
    DefendHandler,
    DefendingComponent,
    FortificationComponent,
    FortifyHandler,
    RaidHandler,
    SparHandler,
    WeaponComponent,
    barbariansim_fragments,
    install_barbariansim,
)
from bunnyland.mechanics.policy import BoundaryTag, install_policy

HOUR = 3600.0


def _install(actor, *, enabled=frozenset({BoundaryTag.PVP})):
    install_policy(actor, enabled=enabled)
    install_barbariansim(actor)
    actor.register_handler(AttackHandler())
    actor.register_handler(SparHandler())
    actor.register_handler(DefendHandler())
    actor.register_handler(ChallengeHandler())
    actor.register_handler(FortifyHandler())
    actor.register_handler(RaidHandler())


def _target(scenario, *, health=20.0, armor=0.0):
    components = [
        IdentityComponent(name="Ash", kind="character"),
        CharacterComponent(species="bunny"),
        HealthComponent(current=health, maximum=20.0),
    ]
    if armor:
        components.append(ArmorComponent(rating=armor))
    target = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), target.id
    )
    return target.id


def _weapon(scenario, damage=8.0):
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Axe", kind="weapon"),
            PortableComponent(can_pick_up=True),
            WeaponComponent(damage=damage, damage_type="slash", lethal_capable=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), item.id
    )
    return item.id


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


async def test_attack_is_blocked_when_pvp_not_enabled():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    target = _target(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "attack", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert scenario.actor.world.get_entity(target).get_component(HealthComponent).current == 20.0
    assert any("pvp" in event.reason for event in rejects)


async def test_attack_damage_respects_weapon_armor_and_defense():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _target(scenario, health=20.0, armor=2.0)
    weapon = _weapon(scenario, damage=10.0)
    target_entity = scenario.actor.world.get_entity(target)
    target_entity.add_component(DefendingComponent(started_at_epoch=0, reduction=3.0))
    attacked: list[CharacterAttackedEvent] = []
    scenario.actor.bus.subscribe(CharacterAttackedEvent, attacked.append)

    await scenario.actor.submit(
        _cmd(scenario, "attack", target_id=str(target), weapon_id=str(weapon))
    )
    await scenario.actor.tick(HOUR)

    assert attacked[0].damage == 5.0
    assert target_entity.get_component(HealthComponent).current == 15.0
    assert not target_entity.has_component(DefendingComponent)


async def test_lethal_attack_requires_lethal_pvp_policy():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset({BoundaryTag.PVP}))
    target = _target(scenario, health=4.0)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "attack", target_id=str(target), lethal=True))
    await scenario.actor.tick(HOUR)

    assert not scenario.actor.world.get_entity(target).has_component(DownedComponent)
    assert any("lethal_pvp" in event.reason for event in rejects)


async def test_lethal_attack_flows_into_existing_downed_consequence():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset({BoundaryTag.PVP, BoundaryTag.LETHAL_PVP}))
    target = _target(scenario, health=4.0)

    await scenario.actor.submit(_cmd(scenario, "attack", target_id=str(target), lethal=True))
    await scenario.actor.tick(HOUR)

    assert scenario.actor.world.get_entity(target).has_component(DownedComponent)


async def test_sparring_is_nonlethal_and_defend_sets_status():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _target(scenario, health=3.0)
    defended: list[CharacterDefendedEvent] = []
    scenario.actor.bus.subscribe(CharacterDefendedEvent, defended.append)

    await scenario.actor.submit(_cmd(scenario, "defend"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "spar", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_component(DefendingComponent)
    assert defended[0].reduction == 2.0
    assert scenario.actor.world.get_entity(target).get_component(HealthComponent).current == 1.0
    assert not scenario.actor.world.get_entity(target).has_component(DownedComponent)


async def test_challenge_emits_roleplay_event_without_pvp_gate():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    target = _target(scenario)
    challenges: list[CombatChallengeEvent] = []
    scenario.actor.bus.subscribe(CombatChallengeEvent, challenges.append)

    await scenario.actor.submit(
        _cmd(scenario, "challenge", target_id=str(target), terms="first touch")
    )
    await scenario.actor.tick(HOUR)

    assert challenges[0].target_id == str(target)
    assert challenges[0].terms == "first touch"


async def test_fortify_current_room_and_raid_damage_fortification():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    built: list[FortificationBuiltEvent] = []
    raids: list[RaidStartedEvent] = []
    scenario.actor.bus.subscribe(FortificationBuiltEvent, built.append)
    scenario.actor.bus.subscribe(RaidStartedEvent, raids.append)

    await scenario.actor.submit(_cmd(scenario, "fortify", strength=2.0))
    await scenario.actor.tick(HOUR)

    room = scenario.actor.world.get_entity(scenario.room_a)
    fortification = room.get_component(FortificationComponent)
    assert fortification.rating == 2.0
    assert fortification.durability == 10.0
    assert built[0].target_id == str(scenario.room_a)

    await scenario.actor.submit(
        _cmd(scenario, "raid", target_id=str(scenario.room_a), intensity=5.0)
    )
    await scenario.actor.tick(HOUR)

    assert raids[0].damage == 3.0
    assert room.get_component(FortificationComponent).durability == 7.0


async def test_fortify_rejects_unreachable_target():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    target = _target(scenario)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, target)
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), target
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "fortify", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert any("not reachable" in event.reason for event in rejects)


def test_barbariansim_fragments_show_defense_armor_and_weapons():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(DefendingComponent(started_at_epoch=0))
    character.add_component(ArmorComponent(rating=1.5))
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        FortificationComponent(rating=2.0, durability=8.0)
    )
    _weapon(scenario)

    fragments = barbariansim_fragments(scenario.actor.world, character)

    assert any("defending" in line for line in fragments)
    assert any("armor rating" in line for line in fragments)
    assert any("Reachable weapon" in line for line in fragments)
    assert any("Reachable fortification" in line for line in fragments)
