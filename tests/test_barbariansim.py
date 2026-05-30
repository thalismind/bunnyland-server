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
    TemperatureComponent,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.events import (
    CharacterAttackedEvent,
    CharacterDefendedEvent,
    CharacterPickpocketedEvent,
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
    DurabilityComponent,
    ExposureDamageEvent,
    FortificationComponent,
    FortifyHandler,
    HeatstrokeStartedEvent,
    ItemBrokenEvent,
    ItemDamagedEvent,
    ItemRepairedEvent,
    PickpocketHandler,
    RaidHandler,
    RepairItemHandler,
    ShelterComponent,
    SparHandler,
    StaminaChangedEvent,
    StaminaComponent,
    TemperatureExposureComponent,
    TemperatureResistanceComponent,
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
    actor.register_handler(RepairItemHandler())
    actor.register_handler(PickpocketHandler())


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


def _durable_weapon(scenario, *, damage=8.0, durability=2.0):
    item_id = _weapon(scenario, damage=damage)
    scenario.actor.world.get_entity(item_id).add_component(
        DurabilityComponent(current=durability, maximum=durability)
    )
    return item_id


def _target_item(scenario, target, name="Coin"):
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="item"), PortableComponent(can_pick_up=True)],
    )
    scenario.actor.world.get_entity(target).add_relationship(
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


async def test_stamina_regenerates_before_attack_and_spends_on_combat():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(StaminaComponent(current=0.0, maximum=10.0, regen_per_hour=5.0))
    target = _target(scenario, health=20.0)
    changed: list[StaminaChangedEvent] = []
    scenario.actor.bus.subscribe(StaminaChangedEvent, changed.append)

    await scenario.actor.submit(_cmd(scenario, "attack", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert character.get_component(StaminaComponent).current == 2.0
    assert scenario.actor.world.get_entity(target).get_component(HealthComponent).current == 15.0
    assert changed[0].reason == "attack"


async def test_weapon_durability_decreases_breaks_and_repair_restores_use():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset({BoundaryTag.PVP}))
    target = _target(scenario, health=20.0)
    weapon = _durable_weapon(scenario, damage=6.0, durability=1.0)
    damaged: list[ItemDamagedEvent] = []
    broken: list[ItemBrokenEvent] = []
    repaired: list[ItemRepairedEvent] = []
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(ItemDamagedEvent, damaged.append)
    scenario.actor.bus.subscribe(ItemBrokenEvent, broken.append)
    scenario.actor.bus.subscribe(ItemRepairedEvent, repaired.append)
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "attack", target_id=str(target), weapon_id=str(weapon))
    )
    await scenario.actor.tick(HOUR)
    assert scenario.actor.world.get_entity(weapon).get_component(DurabilityComponent).broken
    assert damaged[0].durability == 0.0
    assert broken[0].item_id == str(weapon)

    await scenario.actor.submit(
        _cmd(scenario, "attack", target_id=str(target), weapon_id=str(weapon))
    )
    await scenario.actor.tick(HOUR)
    assert any("weapon is not usable" in event.reason for event in rejects)

    await scenario.actor.submit(_cmd(scenario, "repair-item", item_id=str(weapon), amount=1.0))
    await scenario.actor.tick(HOUR)
    durability = scenario.actor.world.get_entity(weapon).get_component(DurabilityComponent)
    assert durability.broken is False
    assert repaired[0].durability == 1.0


async def test_low_stamina_blocks_combat_without_damage():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(StaminaComponent(current=1.0, maximum=10.0, regen_per_hour=0.0))
    target = _target(scenario, health=20.0)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "attack", target_id=str(target)))
    await scenario.actor.tick(0.0)

    assert character.get_component(StaminaComponent).current == 1.0
    assert scenario.actor.world.get_entity(target).get_component(HealthComponent).current == 20.0
    assert any("insufficient stamina" in event.reason for event in rejects)


async def test_hot_room_exposure_damages_health():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(TemperatureComponent(celsius=45.0))
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    character.add_component(TemperatureExposureComponent())
    heatstroke: list[HeatstrokeStartedEvent] = []
    damage: list[ExposureDamageEvent] = []
    scenario.actor.bus.subscribe(HeatstrokeStartedEvent, heatstroke.append)
    scenario.actor.bus.subscribe(ExposureDamageEvent, damage.append)

    await scenario.actor.tick(HOUR)

    exposure = character.get_component(TemperatureExposureComponent)
    assert exposure.heat == 15.0
    assert exposure.heat_danger is True
    assert character.get_component(HealthComponent).current == 15.0
    assert heatstroke[0].character_id == str(scenario.character)
    assert damage[0].cause == "heat exposure"


async def test_cold_room_exposure_damages_health():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(TemperatureComponent(celsius=-10.0))
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    character.add_component(TemperatureExposureComponent())
    damage: list[ExposureDamageEvent] = []
    scenario.actor.bus.subscribe(ExposureDamageEvent, damage.append)

    await scenario.actor.tick(HOUR)

    exposure = character.get_component(TemperatureExposureComponent)
    assert exposure.cold == 15.0
    assert exposure.cold_danger is True
    assert character.get_component(HealthComponent).current == 15.0
    assert damage[0].cause == "cold exposure"


async def test_temperature_resistance_and_shelter_prevent_exposure_damage():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_component(TemperatureComponent(celsius=45.0))
    room.add_component(ShelterComponent(temperature_buffer=5.0))
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    character.add_component(TemperatureExposureComponent())
    character.add_component(TemperatureResistanceComponent(heat=10.0))
    damage: list[ExposureDamageEvent] = []
    scenario.actor.bus.subscribe(ExposureDamageEvent, damage.append)

    await scenario.actor.tick(HOUR)

    exposure = character.get_component(TemperatureExposureComponent)
    assert exposure.heat == 0.0
    assert character.get_component(HealthComponent).current == 20.0
    assert damage == []


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


async def test_pickpocket_requires_pickpocketing_policy():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    target = _target(scenario)
    item = _target_item(scenario, target)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "pickpocket", target_id=str(target), item_id=str(item))
    )
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == target
    assert any("pickpocketing" in event.reason for event in rejects)


async def test_pickpocket_transfers_target_inventory_item_when_enabled():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset({BoundaryTag.PICKPOCKETING}))
    target = _target(scenario)
    item = _target_item(scenario, target)
    pickpocketed: list[CharacterPickpocketedEvent] = []
    scenario.actor.bus.subscribe(CharacterPickpocketedEvent, pickpocketed.append)

    await scenario.actor.submit(
        _cmd(scenario, "pickpocket", target_id=str(target), item_id=str(item))
    )
    await scenario.actor.tick(HOUR)

    assert container_of(scenario.actor.world.get_entity(item)) == scenario.character
    assert pickpocketed[0].target_id == str(target)
    assert pickpocketed[0].item_id == str(item)


def test_barbariansim_fragments_show_defense_armor_and_weapons():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(DefendingComponent(started_at_epoch=0))
    character.add_component(ArmorComponent(rating=1.5))
    character.add_component(StaminaComponent(current=4.0, maximum=10.0))
    character.add_component(TemperatureExposureComponent(heat=12.0, heat_danger=True))
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        FortificationComponent(rating=2.0, durability=8.0)
    )
    _durable_weapon(scenario)

    fragments = barbariansim_fragments(scenario.actor.world, character)

    assert any("defending" in line for line in fragments)
    assert any("Stamina: 4/10" in line for line in fragments)
    assert any("dangerous heat exposure" in line for line in fragments)
    assert any("armor rating" in line for line in fragments)
    assert any("Reachable weapon" in line for line in fragments)
    assert any("durability 2/2" in line for line in fragments)
    assert any("Reachable fortification" in line for line in fragments)
