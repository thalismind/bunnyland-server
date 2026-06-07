"""Tests for barbarian-sim PvP, combat, and roleplay."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DownedComponent,
    HandlerContext,
    HealthComponent,
    IdentityComponent,
    Lane,
    PortableComponent,
    RoomComponent,
    TemperatureComponent,
    Wearing,
    build_submitted_command,
    container_of,
    replace_component,
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
    CharacterPoisonedEvent,
    CleanseCorruptionHandler,
    CorruptionCleansedEvent,
    CorruptionComponent,
    CorruptionGainedEvent,
    DefendHandler,
    DefendingComponent,
    DurabilityComponent,
    ExposureDamageEvent,
    FortificationComponent,
    FortifyHandler,
    GainCorruptionHandler,
    HeatstrokeStartedEvent,
    ItemBrokenEvent,
    ItemDamagedEvent,
    ItemRepairedEvent,
    PickpocketHandler,
    PoisonCharacterHandler,
    PoisonComponent,
    PoisonProgressedEvent,
    PoisonTreatedEvent,
    RaidHandler,
    RepairItemHandler,
    ShelterComponent,
    SparHandler,
    StaminaChangedEvent,
    StaminaComponent,
    TemperatureExposureComponent,
    TemperatureResistanceComponent,
    TreatPoisonHandler,
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
    actor.register_handler(PoisonCharacterHandler())
    actor.register_handler(TreatPoisonHandler())
    actor.register_handler(GainCorruptionHandler())
    actor.register_handler(CleanseCorruptionHandler())
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


def _handler_cmd(scenario, command_type, *, character_id=None, **payload):
    return build_submitted_command(
        character_id=str(scenario.character) if character_id is None else character_id,
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


async def test_attack_rejects_unreachable_or_non_weapon_weapon_ids():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _target(scenario)
    distant_weapon = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Axe", kind="weapon"),
            PortableComponent(can_pick_up=True),
            WeaponComponent(damage=10.0, damage_type="slash", lethal_capable=True),
        ],
    )
    non_weapon = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Rock", kind="item"), PortableComponent(can_pick_up=True)],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), non_weapon.id
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "attack", target_id=str(target), weapon_id=str(distant_weapon.id))
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.submit(
        _cmd(scenario, "attack", target_id=str(target), weapon_id=str(non_weapon.id))
    )
    await scenario.actor.tick(0.0)

    assert [event.reason for event in rejects] == [
        "weapon is not usable",
        "weapon is not usable",
    ]
    assert scenario.actor.world.get_entity(target).get_component(HealthComponent).current == 20.0


async def test_attack_damage_accumulates_worn_armor_rating():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _target(scenario, health=20.0, armor=2.0)
    armor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hide vest", kind="armor"),
            PortableComponent(can_pick_up=True),
            ArmorComponent(rating=3.0),
        ],
    )
    target_entity = scenario.actor.world.get_entity(target)
    target_entity.add_relationship(Contains(mode=ContainmentMode.INVENTORY), armor.id)
    target_entity.add_relationship(Wearing(slot="torso"), armor.id)
    weapon = _weapon(scenario, damage=10.0)
    attacked: list[CharacterAttackedEvent] = []
    scenario.actor.bus.subscribe(CharacterAttackedEvent, attacked.append)

    await scenario.actor.submit(
        _cmd(scenario, "attack", target_id=str(target), weapon_id=str(weapon))
    )
    await scenario.actor.tick(HOUR)

    assert attacked[0].damage == 5.0
    assert target_entity.get_component(HealthComponent).current == 15.0


async def test_attack_rejects_bad_targets_before_damage_resolution():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    missing_target = "entity_999"
    downed_target = _target(scenario)
    scenario.actor.world.get_entity(downed_target).add_component(
        DownedComponent(downed_at_epoch=0, cause="test")
    )
    distant_target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Ash", kind="character"),
            CharacterComponent(species="bunny"),
            HealthComponent(current=20.0, maximum=20.0),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant_target.id
    )
    no_health_target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Training Dummy", kind="character"),
            CharacterComponent(species="dummy"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), no_health_target.id
    )
    for target_id, reason in (
        ("not-an-id", "invalid attacker or target id"),
        (missing_target, "target does not exist"),
        (str(downed_target), "target cannot fight"),
        (str(distant_target.id), "target is not present"),
        (str(no_health_target.id), "target has no health"),
    ):
        result = AttackHandler().execute(ctx, _cmd(scenario, "attack", target_id=target_id))
        assert result.ok is False
        assert result.reason == reason


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


async def test_character_shelter_and_indoor_room_buffer_temperature():
    scenario = build_scenario()
    _install(scenario.actor)
    room = scenario.actor.world.get_entity(scenario.room_a)
    replace_component(room, RoomComponent(title="Mosslit Burrow", indoor=True))
    room.add_component(TemperatureComponent(celsius=40.0))
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=20.0, maximum=20.0))
    character.add_component(TemperatureExposureComponent())
    character.add_component(ShelterComponent(temperature_buffer=6.0))
    damage: list[ExposureDamageEvent] = []
    scenario.actor.bus.subscribe(ExposureDamageEvent, damage.append)

    await scenario.actor.tick(HOUR)

    exposure = character.get_component(TemperatureExposureComponent)
    assert exposure.heat == 0.0
    assert character.get_component(HealthComponent).current == 20.0
    assert damage == []


async def test_temperature_exposure_recovers_without_ambient_room():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(TemperatureExposureComponent(heat=6.0, cold=3.0))

    await scenario.actor.tick(HOUR)

    exposure = character.get_component(TemperatureExposureComponent)
    assert exposure.heat == 2.0
    assert exposure.cold == 0.0
    assert exposure.heat_danger is False
    assert exposure.cold_danger is False


async def test_poison_progresses_damages_health_and_can_be_treated():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _target(scenario, health=20.0)
    poisoned: list[CharacterPoisonedEvent] = []
    progressed: list[PoisonProgressedEvent] = []
    treated: list[PoisonTreatedEvent] = []
    scenario.actor.bus.subscribe(CharacterPoisonedEvent, poisoned.append)
    scenario.actor.bus.subscribe(PoisonProgressedEvent, progressed.append)
    scenario.actor.bus.subscribe(PoisonTreatedEvent, treated.append)

    await scenario.actor.submit(
        _cmd(scenario, "poison-character", target_id=str(target), severity=2.0)
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR)

    target_entity = scenario.actor.world.get_entity(target)
    assert target_entity.has_component(PoisonComponent)
    assert target_entity.get_component(HealthComponent).current == 18.0
    assert poisoned[0].severity == 2.0
    assert progressed[0].damage == 2.0

    await scenario.actor.submit(_cmd(scenario, "treat-poison", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert not target_entity.has_component(PoisonComponent)
    assert treated[0].character_id == str(target)


async def test_corruption_can_be_gained_and_cleansed():
    scenario = build_scenario()
    _install(scenario.actor)
    gained: list[CorruptionGainedEvent] = []
    cleansed: list[CorruptionCleansedEvent] = []
    scenario.actor.bus.subscribe(CorruptionGainedEvent, gained.append)
    scenario.actor.bus.subscribe(CorruptionCleansedEvent, cleansed.append)

    await scenario.actor.submit(_cmd(scenario, "gain-corruption", amount=3.0))
    await scenario.actor.tick(HOUR)
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(CorruptionComponent).amount == 3.0
    assert gained[0].amount == 3.0

    await scenario.actor.submit(_cmd(scenario, "cleanse-corruption"))
    await scenario.actor.tick(HOUR)

    assert not character.has_component(CorruptionComponent)
    assert cleansed[0].character_id == str(scenario.character)


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


def test_barbariansim_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = _target(scenario)
    downed_target = _target(scenario)
    scenario.actor.world.get_entity(downed_target).add_component(
        DownedComponent(downed_at_epoch=0, cause="test")
    )
    distant_target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Ash", kind="character"),
            CharacterComponent(species="bunny"),
            HealthComponent(current=20.0, maximum=20.0),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant_target.id
    )
    unreachable_target = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="hidden cache", kind="cache")],
    )
    non_durable_item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain rock", kind="item"), PortableComponent()],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), non_durable_item.id
    )
    durable_item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="cracked axe", kind="weapon"),
            PortableComponent(),
            DurabilityComponent(current=1.0, maximum=2.0),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), durable_item.id
    )
    distant_item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far coin", kind="item"),
            PortableComponent(),
            DurabilityComponent(current=1.0, maximum=2.0),
        ],
    )
    inventory_item = _target_item(scenario, target, name="Coin")
    stuck_item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="stuck charm", kind="item"),
            PortableComponent(can_pick_up=False),
        ],
    )
    scenario.actor.world.get_entity(target).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), stuck_item.id
    )

    cases = [
        (
            DefendHandler(),
            _handler_cmd(scenario, "defend", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            ChallengeHandler(),
            _handler_cmd(scenario, "challenge", target_id="not-an-id"),
            "invalid challenger or target id",
        ),
        (
            ChallengeHandler(),
            _handler_cmd(scenario, "challenge", target_id="entity_999"),
            "target does not exist",
        ),
        (
            ChallengeHandler(),
            _handler_cmd(scenario, "challenge", target_id=str(distant_target.id)),
            "target is not present",
        ),
        (
            FortifyHandler(),
            _handler_cmd(scenario, "fortify", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            FortifyHandler(),
            _handler_cmd(scenario, "fortify", target_id="entity_999"),
            "target does not exist",
        ),
        (
            FortifyHandler(),
            _handler_cmd(scenario, "fortify", target_id=str(unreachable_target.id)),
            "target is not reachable",
        ),
        (
            FortifyHandler(),
            _handler_cmd(scenario, "fortify", strength=0),
            "fortification strength must be positive",
        ),
        (
            RaidHandler(),
            _handler_cmd(scenario, "raid", target_id="not-an-id"),
            "invalid raider or target id",
        ),
        (
            RaidHandler(),
            _handler_cmd(scenario, "raid", target_id="entity_999"),
            "target does not exist",
        ),
        (
            RaidHandler(),
            _handler_cmd(scenario, "raid", target_id=str(unreachable_target.id)),
            "target is not reachable",
        ),
        (
            RaidHandler(),
            _handler_cmd(scenario, "raid", target_id=str(target), intensity=0),
            "raid intensity must be positive",
        ),
        (
            RepairItemHandler(),
            _handler_cmd(scenario, "repair-item", item_id="not-an-id"),
            "invalid character or item id",
        ),
        (
            RepairItemHandler(),
            _handler_cmd(scenario, "repair-item", item_id="entity_999"),
            "item does not exist",
        ),
        (
            RepairItemHandler(),
            _handler_cmd(scenario, "repair-item", item_id=str(distant_item.id)),
            "item is not reachable",
        ),
        (
            RepairItemHandler(),
            _handler_cmd(scenario, "repair-item", item_id=str(non_durable_item.id)),
            "item has no durability",
        ),
        (
            RepairItemHandler(),
            _handler_cmd(scenario, "repair-item", item_id=str(durable_item.id), amount=0),
            "repair amount must be positive",
        ),
        (
            PoisonCharacterHandler(),
            _handler_cmd(scenario, "poison-character", target_id="not-an-id"),
            "invalid actor or target id",
        ),
        (
            PoisonCharacterHandler(),
            _handler_cmd(scenario, "poison-character", target_id="entity_999"),
            "target does not exist",
        ),
        (
            PoisonCharacterHandler(),
            _handler_cmd(scenario, "poison-character", target_id=str(distant_target.id)),
            "target is not present",
        ),
        (
            PoisonCharacterHandler(),
            _handler_cmd(scenario, "poison-character", target_id=str(target), severity=0),
            "poison severity must be positive",
        ),
        (
            TreatPoisonHandler(),
            _handler_cmd(scenario, "treat-poison", target_id="not-an-id"),
            "invalid actor or target id",
        ),
        (
            TreatPoisonHandler(),
            _handler_cmd(scenario, "treat-poison", target_id="entity_999"),
            "target does not exist",
        ),
        (
            TreatPoisonHandler(),
            _handler_cmd(scenario, "treat-poison", target_id=str(distant_target.id)),
            "target is not present",
        ),
        (
            TreatPoisonHandler(),
            _handler_cmd(scenario, "treat-poison", target_id=str(target)),
            "target is not poisoned",
        ),
        (
            GainCorruptionHandler(),
            _handler_cmd(scenario, "gain-corruption", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            GainCorruptionHandler(),
            _handler_cmd(scenario, "gain-corruption", amount=0),
            "corruption amount must be positive",
        ),
        (
            CleanseCorruptionHandler(),
            _handler_cmd(scenario, "cleanse-corruption", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            CleanseCorruptionHandler(),
            _handler_cmd(scenario, "cleanse-corruption"),
            "character is not corrupted",
        ),
        (
            PickpocketHandler(),
            _handler_cmd(
                scenario,
                "pickpocket",
                target_id="not-an-id",
                item_id=str(inventory_item),
            ),
            "invalid thief, target, or item id",
        ),
        (
            PickpocketHandler(),
            _handler_cmd(
                scenario,
                "pickpocket",
                target_id="entity_999",
                item_id=str(inventory_item),
            ),
            "target or item does not exist",
        ),
        (
            PickpocketHandler(),
            _handler_cmd(
                scenario,
                "pickpocket",
                target_id=str(downed_target),
                item_id=str(inventory_item),
            ),
            "target cannot be pickpocketed",
        ),
        (
            PickpocketHandler(),
            _handler_cmd(
                scenario,
                "pickpocket",
                target_id=str(distant_target.id),
                item_id=str(inventory_item),
            ),
            "target is not present",
        ),
        (
            PickpocketHandler(),
            _handler_cmd(
                scenario,
                "pickpocket",
                target_id=str(target),
                item_id=str(durable_item.id),
            ),
            "item is not in target inventory",
        ),
        (
            PickpocketHandler(),
            _handler_cmd(scenario, "pickpocket", target_id=str(target), item_id=str(stuck_item.id)),
            "item cannot be taken",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


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
    character.add_component(PoisonComponent(severity=2.0))
    character.add_component(CorruptionComponent(amount=3.0))
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        FortificationComponent(rating=2.0, durability=8.0)
    )
    _durable_weapon(scenario)

    fragments = barbariansim_fragments(scenario.actor.world, character)

    assert any("defending" in line for line in fragments)
    assert any("Stamina: 4/10" in line for line in fragments)
    assert any("dangerous heat exposure" in line for line in fragments)
    assert any("Poisoned: severity 2" in line for line in fragments)
    assert any("Corruption: 3" in line for line in fragments)
    assert any("armor rating" in line for line in fragments)
    assert any("Reachable weapon" in line for line in fragments)
    assert any("durability 2/2" in line for line in fragments)
    assert any("Reachable fortification" in line for line in fragments)
