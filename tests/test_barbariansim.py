"""Tests for barbarian-sim PvP, combat, and roleplay."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import build_scenario

from bunnyland.core import (
    BodyPlanComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    DownedComponent,
    GenerationIntentComponent,
    HandlerContext,
    HasInjury,
    HealthComponent,
    IdentityComponent,
    Lane,
    PortableComponent,
    RoomComponent,
    TemperatureComponent,
    Wearing,
    build_submitted_command,
    container_of,
    parse_entity_id,
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
from bunnyland.foundation.policy.mechanics import BoundaryTag, install_policy
from bunnyland.foundation.storyteller.mechanics import (
    IncidentBudgetComponent,
    IncidentComponent,
    IncidentGeneratedEvent,
    IncidentSpawned,
    StorytellerComponent,
    StorytellerConsequence,
    default_incident_definitions,
)
from bunnyland.prompts import ComponentPromptContext, PromptPerspective
from bunnyland.simpacks.barbariansim.incidents import BARBARIAN_RAID
from bunnyland.simpacks.barbariansim.mechanics import (
    ArmorComponent,
    AttackHandler,
    BarbarianRaidEnrichment,
    BarbarianSimPolicyComponent,
    BaseClaimComponent,
    BaseClaimedEvent,
    BlessingComponent,
    BossComponent,
    BridgeSurvivalGapHandler,
    BuildingComponent,
    ChallengeHandler,
    CharacterPoisonedEvent,
    ClaimBaseHandler,
    ClaimTreasureHandler,
    CleanseCorruptionHandler,
    ClimbHandler,
    ClimbingGateComponent,
    ClimbingSkillComponent,
    CommandFollowerHandler,
    CorruptionCleansedEvent,
    CorruptionComponent,
    CorruptionGainedEvent,
    CurseComponent,
    DangerZoneComponent,
    DecayBuildingHandler,
    DefeatBossHandler,
    DefendHandler,
    DefendingComponent,
    DemolishBuildingHandler,
    DisarmTrapHandler,
    DurabilityComponent,
    ExploreDangerZoneHandler,
    ExposureDamageEvent,
    FollowerComponent,
    FollowerOrderChangedEvent,
    FollowerRecruitedEvent,
    FortificationComponent,
    FortifyHandler,
    GainCorruptionHandler,
    HeatstrokeStartedEvent,
    ItemBrokenEvent,
    ItemDamagedEvent,
    ItemRepairedEvent,
    KeyComponent,
    PerformRitualHandler,
    PickpocketHandler,
    PlaceTrapHandler,
    PoisonCharacterHandler,
    PoisonComponent,
    PoisonProgressedEvent,
    PoisonTreatedEvent,
    PrepareSiegeHandler,
    PurgeWaveComponent,
    RaiderSpawnSpec,
    RaidHandler,
    RecruitFollowerHandler,
    ReleaseThrallHandler,
    RepairItemHandler,
    RitualComponent,
    ShelterComponent,
    ShrineComponent,
    SiegeReadinessComponent,
    SparHandler,
    StaminaChangedEvent,
    StaminaComponent,
    StartPurgeWaveHandler,
    SubdueHandler,
    SurvivalGapComponent,
    TemperatureExposureComponent,
    TemperatureResistanceComponent,
    ThrallComponent,
    ThrallReleasedEvent,
    ThrallTakenEvent,
    TrapComponent,
    TrapDisarmedEvent,
    TrapPlacedEvent,
    TreasureComponent,
    TreatPoisonHandler,
    UnlockTreasureHandler,
    UpgradeBuildingHandler,
    WeaponComponent,
    barbariansim_fragments,
    ensure_barbariansim_policy,
    generate_raid_spawn_specs,
    install_barbariansim,
)
from bunnyland.simpacks.barbariansim.mechanics import _ambient_celsius as ambient_celsius
from bunnyland.simpacks.barbariansim.mechanics import _armor_rating as armor_rating
from bunnyland.simpacks.barbariansim.mechanics import _damage_item as damage_item
from bunnyland.simpacks.colonysim.mechanics import install_colonysim

HOUR = 3600.0


def _install(actor, *, enabled=frozenset({BoundaryTag.PVP})):
    install_policy(actor, enabled=enabled)
    install_barbariansim(actor)
    actor.register_handler(AttackHandler())
    actor.register_handler(SparHandler())
    actor.register_handler(DefendHandler())
    actor.register_handler(ChallengeHandler())
    actor.register_handler(FortifyHandler())
    actor.register_handler(ClaimBaseHandler())
    actor.register_handler(PlaceTrapHandler())
    actor.register_handler(DisarmTrapHandler())
    actor.register_handler(RaidHandler())
    actor.register_handler(RepairItemHandler())
    actor.register_handler(PoisonCharacterHandler())
    actor.register_handler(TreatPoisonHandler())
    actor.register_handler(GainCorruptionHandler())
    actor.register_handler(CleanseCorruptionHandler())
    actor.register_handler(PickpocketHandler())
    actor.register_handler(SubdueHandler())
    actor.register_handler(RecruitFollowerHandler())
    actor.register_handler(CommandFollowerHandler())
    actor.register_handler(ReleaseThrallHandler())


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


def _room_entity(scenario, name, kind, components):
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), *components],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


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


def test_barbariansim_parity_handlers_mutate_reachable_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(ClimbingSkillComponent(level=2))

    gap = _room_entity(
        scenario,
        "no shelter",
        "survival-gap",
        [SurvivalGapComponent(gap_type="shelter")],
    )
    building = _room_entity(
        scenario,
        "log wall",
        "building",
        [BuildingComponent(integrity=8.0, maximum_integrity=10.0)],
    )
    base = _room_entity(scenario, "river camp", "base", [])
    shrine = _room_entity(
        scenario,
        "stone shrine",
        "shrine",
        [ShrineComponent(deity="ember")],
    )
    ritual = _room_entity(
        scenario,
        "ember blessing",
        "ritual",
        [RitualComponent(blessing="ember", curse="ash", corruption_cost=1.0)],
    )
    zone = _room_entity(
        scenario,
        "serpent pass",
        "danger-zone",
        [DangerZoneComponent(zone_type="pass", danger_rating=3.0)],
    )
    boss = _room_entity(
        scenario,
        "serpent queen",
        "boss",
        [BossComponent(name="serpent queen")],
    )
    treasure = _room_entity(
        scenario,
        "sealed hoard",
        "treasure",
        [TreasureComponent(treasure_type="hoard", key_name="serpent")],
    )
    gate = _room_entity(
        scenario,
        "cliff path",
        "climbing-gate",
        [ClimbingGateComponent(required_level=2)],
    )
    key = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="serpent key", kind="key"),
            PortableComponent(can_pick_up=True),
            KeyComponent(key_name="serpent"),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), key.id)

    calls = [
        (BridgeSurvivalGapHandler(), "bridge-survival-gap", {"gap_id": str(gap.id)}),
        (
            DecayBuildingHandler(),
            "decay-building",
            {"building_id": str(building.id), "amount": 2},
        ),
        (
            UpgradeBuildingHandler(),
            "upgrade-building",
            {"building_id": str(building.id), "integrity": 4},
        ),
        (
            DemolishBuildingHandler(),
            "demolish-building",
            {"building_id": str(building.id)},
        ),
        (PrepareSiegeHandler(), "prepare-siege", {"base_id": str(base.id), "score": 3}),
        (
            StartPurgeWaveHandler(),
            "start-purge-wave",
            {"base_id": str(base.id), "intensity": 4},
        ),
        (
            PerformRitualHandler(),
            "perform-ritual",
            {"shrine_id": str(shrine.id), "ritual_id": str(ritual.id)},
        ),
        (
            ExploreDangerZoneHandler(),
            "explore-danger-zone",
            {"zone_id": str(zone.id)},
        ),
        (DefeatBossHandler(), "defeat-boss", {"boss_id": str(boss.id)}),
        (
            UnlockTreasureHandler(),
            "unlock-treasure",
            {"treasure_id": str(treasure.id), "key_id": str(key.id)},
        ),
        (ClaimTreasureHandler(), "claim-treasure", {"treasure_id": str(treasure.id)}),
        (ClimbHandler(), "climb", {"gate_id": str(gate.id)}),
    ]

    for handler, command_type, payload in calls:
        result = handler.execute(ctx, _handler_cmd(scenario, command_type, **payload))
        assert result.ok, (command_type, result.reason)

    assert gap.get_component(SurvivalGapComponent).bridged_by == str(scenario.character)
    assert building.get_component(BuildingComponent).demolished is True
    assert base.get_component(SiegeReadinessComponent).score == 3
    assert base.get_component(PurgeWaveComponent).active is True
    assert character.has_component(BlessingComponent)
    assert character.has_component(CurseComponent)
    assert boss.get_component(BossComponent).defeated is True
    assert treasure.get_component(TreasureComponent).claimed_by == str(scenario.character)
    assert gate.get_component(ClimbingGateComponent).opened_by == str(scenario.character)
    fragments = barbariansim_fragments(scenario.actor.world, character)
    assert "Blessing: ember." in fragments
    assert "Curse: ash severity 1." in fragments
    assert "Climbing skill: 2." in fragments
    assert "Survival gap: shelter severity 1 (bridged)." in fragments
    assert "Boss nearby: serpent queen (defeated)." in fragments
    assert "Treasure nearby: hoard (unlocked)." in fragments


def test_barbariansim_parity_handlers_reject_invalid_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    fake = "entity_999999"
    cases = [
        (
            BridgeSurvivalGapHandler(),
            "bridge-survival-gap",
            {"gap_id": fake},
            "invalid character or gap id",
            "survival gap does not exist",
        ),
        (
            DecayBuildingHandler(),
            "decay-building",
            {"building_id": fake},
            "invalid character or building id",
            "building does not exist",
        ),
        (
            UpgradeBuildingHandler(),
            "upgrade-building",
            {"building_id": fake},
            "invalid character or building id",
            "building does not exist",
        ),
        (
            DemolishBuildingHandler(),
            "demolish-building",
            {"building_id": fake},
            "invalid character or building id",
            "building does not exist",
        ),
        (
            PrepareSiegeHandler(),
            "prepare-siege",
            {"base_id": fake},
            "invalid character id",
            "base does not exist",
        ),
        (
            StartPurgeWaveHandler(),
            "start-purge-wave",
            {"base_id": fake},
            "invalid character id",
            "base does not exist",
        ),
        (
            PerformRitualHandler(),
            "perform-ritual",
            {"shrine_id": fake, "ritual_id": fake},
            "invalid character, shrine, or ritual id",
            "shrine or ritual does not exist",
        ),
        (
            ExploreDangerZoneHandler(),
            "explore-danger-zone",
            {"zone_id": fake},
            "invalid character or zone id",
            "danger zone does not exist",
        ),
        (
            DefeatBossHandler(),
            "defeat-boss",
            {"boss_id": fake},
            "invalid character or boss id",
            "boss does not exist",
        ),
        (
            UnlockTreasureHandler(),
            "unlock-treasure",
            {"treasure_id": fake, "key_id": fake},
            "invalid character or treasure id",
            "treasure does not exist",
        ),
        (
            ClaimTreasureHandler(),
            "claim-treasure",
            {"treasure_id": fake},
            "invalid character or treasure id",
            "treasure does not exist",
        ),
        (
            ClimbHandler(),
            "climb",
            {"gate_id": fake},
            "invalid character or climbing gate id",
            "climbing gate does not exist",
        ),
    ]

    for handler, command_type, payload, invalid_reason, missing_reason in cases:
        bad_character = handler.execute(
            ctx,
            _handler_cmd(scenario, command_type, character_id="not-an-id", **payload),
        )
        assert bad_character.ok is False
        assert bad_character.reason == invalid_reason
        missing_target = handler.execute(ctx, _handler_cmd(scenario, command_type, **payload))
        assert missing_target.ok is False
        assert missing_target.reason == missing_reason


def test_barbariansim_parity_handlers_reject_wrong_kind_and_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    wrong_kind = _room_entity(scenario, "plain stone", "prop", [])
    distant_gap = spawn_entity(world, [SurvivalGapComponent()])
    distant_building = spawn_entity(world, [BuildingComponent()])
    distant_base = spawn_entity(world, [RoomComponent(title="Far Base")])
    distant_shrine = spawn_entity(world, [ShrineComponent()])
    ritual = _room_entity(scenario, "rite", "ritual", [RitualComponent()])
    shrine = _room_entity(scenario, "shrine", "shrine", [ShrineComponent()])
    bridged_gap = _room_entity(
        scenario,
        "bridged gap",
        "survival-gap",
        [SurvivalGapComponent(bridged_by=str(scenario.character))],
    )
    building = _room_entity(scenario, "hut", "building", [BuildingComponent()])
    demolished_building = _room_entity(
        scenario,
        "rubble",
        "building",
        [BuildingComponent(demolished=True)],
    )
    performed_ritual = _room_entity(
        scenario,
        "old rite",
        "ritual",
        [RitualComponent(performed_by=(str(scenario.character),))],
    )
    zone = _room_entity(scenario, "ruin", "danger-zone", [DangerZoneComponent()])
    distant_zone = spawn_entity(world, [DangerZoneComponent()])
    boss = _room_entity(scenario, "boss", "boss", [BossComponent(defeated=True)])
    distant_boss = spawn_entity(world, [BossComponent()])
    locked_treasure = _room_entity(
        scenario,
        "locked cache",
        "treasure",
        [TreasureComponent(key_name="serpent")],
    )
    unlocked_treasure = _room_entity(
        scenario,
        "open cache",
        "treasure",
        [TreasureComponent(locked=False)],
    )
    claimed_treasure = _room_entity(
        scenario,
        "claimed cache",
        "treasure",
        [TreasureComponent(locked=False, claimed_by="other")],
    )
    wrong_key = spawn_entity(
        world,
        [
            IdentityComponent(name="wrong key", kind="key"),
            PortableComponent(can_pick_up=True),
            KeyComponent(key_name="wrong"),
        ],
    )
    world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), wrong_key.id
    )
    gate = _room_entity(
        scenario,
        "cliff",
        "climbing-gate",
        [ClimbingGateComponent(required_level=2)],
    )
    distant_gate = spawn_entity(world, [ClimbingGateComponent()])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), distant_base.id)

    cases = [
        (
            BridgeSurvivalGapHandler(),
            _handler_cmd(scenario, "bridge-survival-gap", gap_id=str(distant_gap.id)),
            "survival gap is not reachable",
        ),
        (
            BridgeSurvivalGapHandler(),
            _handler_cmd(scenario, "bridge-survival-gap", gap_id=str(wrong_kind.id)),
            "target is not a survival gap",
        ),
        (
            BridgeSurvivalGapHandler(),
            _handler_cmd(scenario, "bridge-survival-gap", gap_id=str(bridged_gap.id)),
            "survival gap is already bridged",
        ),
        (
            DecayBuildingHandler(),
            _handler_cmd(scenario, "decay-building", building_id=str(distant_building.id)),
            "building is not reachable",
        ),
        (
            DecayBuildingHandler(),
            _handler_cmd(scenario, "decay-building", building_id=str(wrong_kind.id)),
            "target is not a building",
        ),
        (
            DecayBuildingHandler(),
            _handler_cmd(scenario, "decay-building", building_id=str(demolished_building.id)),
            "building is demolished",
        ),
        (
            DecayBuildingHandler(),
            _handler_cmd(scenario, "decay-building", building_id=str(building.id), amount=0),
            "decay amount must be positive",
        ),
        (
            UpgradeBuildingHandler(),
            _handler_cmd(scenario, "upgrade-building", building_id=str(wrong_kind.id)),
            "target is not a building",
        ),
        (
            UpgradeBuildingHandler(),
            _handler_cmd(scenario, "upgrade-building", building_id=str(demolished_building.id)),
            "building is demolished",
        ),
        (
            UpgradeBuildingHandler(),
            _handler_cmd(scenario, "upgrade-building", building_id=str(building.id), integrity=0),
            "upgrade integrity must be positive",
        ),
        (
            DemolishBuildingHandler(),
            _handler_cmd(scenario, "demolish-building", building_id=str(wrong_kind.id)),
            "target is not a building",
        ),
        (
            DemolishBuildingHandler(),
            _handler_cmd(scenario, "demolish-building", building_id=str(demolished_building.id)),
            "building is already demolished",
        ),
        (
            PrepareSiegeHandler(),
            _handler_cmd(scenario, "prepare-siege", base_id=str(distant_base.id), score=0),
            "siege score must be positive",
        ),
        (
            StartPurgeWaveHandler(),
            _handler_cmd(scenario, "start-purge-wave", base_id=str(distant_base.id), intensity=0),
            "purge intensity must be positive",
        ),
        (
            PerformRitualHandler(),
            _handler_cmd(
                scenario,
                "perform-ritual",
                shrine_id=str(distant_shrine.id),
                ritual_id=str(ritual.id),
            ),
            "shrine or ritual is not reachable",
        ),
        (
            PerformRitualHandler(),
            _handler_cmd(
                scenario,
                "perform-ritual",
                shrine_id=str(wrong_kind.id),
                ritual_id=str(ritual.id),
            ),
            "target is not a shrine",
        ),
        (
            PerformRitualHandler(),
            _handler_cmd(
                scenario,
                "perform-ritual",
                shrine_id=str(shrine.id),
                ritual_id=str(wrong_kind.id),
            ),
            "target is not a ritual",
        ),
        (
            PerformRitualHandler(),
            _handler_cmd(
                scenario,
                "perform-ritual",
                shrine_id=str(shrine.id),
                ritual_id=str(performed_ritual.id),
            ),
            "ritual already performed",
        ),
        (
            ExploreDangerZoneHandler(),
            _handler_cmd(scenario, "explore-danger-zone", zone_id=str(distant_zone.id)),
            "danger zone is not reachable",
        ),
        (
            ExploreDangerZoneHandler(),
            _handler_cmd(scenario, "explore-danger-zone", zone_id=str(wrong_kind.id)),
            "target is not a danger zone",
        ),
        (
            DefeatBossHandler(),
            _handler_cmd(scenario, "defeat-boss", boss_id=str(distant_boss.id)),
            "boss is not reachable",
        ),
        (
            DefeatBossHandler(),
            _handler_cmd(scenario, "defeat-boss", boss_id=str(wrong_kind.id)),
            "target is not a boss",
        ),
        (
            DefeatBossHandler(),
            _handler_cmd(scenario, "defeat-boss", boss_id=str(boss.id)),
            "boss is already defeated",
        ),
        (
            UnlockTreasureHandler(),
            _handler_cmd(scenario, "unlock-treasure", treasure_id=str(wrong_kind.id)),
            "target is not treasure",
        ),
        (
            UnlockTreasureHandler(),
            _handler_cmd(scenario, "unlock-treasure", treasure_id=str(unlocked_treasure.id)),
            "treasure is already unlocked",
        ),
        (
            UnlockTreasureHandler(),
            _handler_cmd(
                scenario,
                "unlock-treasure",
                treasure_id=str(locked_treasure.id),
                key_id="entity_999",
            ),
            "required key is not carried",
        ),
        (
            UnlockTreasureHandler(),
            _handler_cmd(
                scenario,
                "unlock-treasure",
                treasure_id=str(locked_treasure.id),
                key_id=str(wrong_key.id),
            ),
            "wrong key",
        ),
        (
            ClaimTreasureHandler(),
            _handler_cmd(scenario, "claim-treasure", treasure_id=str(wrong_kind.id)),
            "target is not treasure",
        ),
        (
            ClaimTreasureHandler(),
            _handler_cmd(scenario, "claim-treasure", treasure_id=str(locked_treasure.id)),
            "treasure is locked",
        ),
        (
            ClaimTreasureHandler(),
            _handler_cmd(scenario, "claim-treasure", treasure_id=str(claimed_treasure.id)),
            "treasure is already claimed",
        ),
        (
            ClimbHandler(),
            _handler_cmd(scenario, "climb", gate_id=str(distant_gate.id)),
            "climbing gate is not reachable",
        ),
        (
            ClimbHandler(),
            _handler_cmd(scenario, "climb", gate_id=str(wrong_kind.id)),
            "target is not a climbing gate",
        ),
        (
            ClimbHandler(),
            _handler_cmd(scenario, "climb", gate_id=str(gate.id)),
            "climbing skill is too low",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    assert (
        ExploreDangerZoneHandler()
        .execute(ctx, _handler_cmd(scenario, "explore-danger-zone", zone_id=str(zone.id)))
        .ok
    )
    assert (
        ExploreDangerZoneHandler()
        .execute(ctx, _handler_cmd(scenario, "explore-danger-zone", zone_id=str(zone.id)))
        .ok
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
    claimed_room = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="claimed camp", kind="room"),
            RoomComponent(title="claimed camp"),
            BaseClaimComponent(claimed_by=str(scenario.character)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), claimed_room.id
    )
    trap = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="snare", kind="trap"), TrapComponent()],
    )
    disarmed_trap = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="sprung snare", kind="trap"), TrapComponent(armed=False)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), trap.id
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), disarmed_trap.id
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
            ClaimBaseHandler(),
            _handler_cmd(scenario, "claim-base", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            ClaimBaseHandler(),
            _handler_cmd(scenario, "claim-base", base_id="entity_999"),
            "base does not exist",
        ),
        (
            ClaimBaseHandler(),
            _handler_cmd(scenario, "claim-base", base_id=str(unreachable_target.id)),
            "base is not reachable",
        ),
        (
            ClaimBaseHandler(),
            _handler_cmd(scenario, "claim-base", base_id=str(claimed_room.id)),
            "base is already claimed",
        ),
        (
            PlaceTrapHandler(),
            _handler_cmd(scenario, "place-trap", character_id="not-an-id"),
            "invalid character id",
        ),
        (
            PlaceTrapHandler(),
            _handler_cmd(scenario, "place-trap", damage=0),
            "trap damage must be positive",
        ),
        (
            DisarmTrapHandler(),
            _handler_cmd(scenario, "disarm-trap", trap_id="not-an-id"),
            "invalid character or trap id",
        ),
        (
            DisarmTrapHandler(),
            _handler_cmd(scenario, "disarm-trap", trap_id="entity_999"),
            "trap does not exist",
        ),
        (
            DisarmTrapHandler(),
            _handler_cmd(scenario, "disarm-trap", trap_id=str(unreachable_target.id)),
            "trap is not reachable",
        ),
        (
            DisarmTrapHandler(),
            _handler_cmd(scenario, "disarm-trap", trap_id=str(non_durable_item.id)),
            "target is not a trap",
        ),
        (
            DisarmTrapHandler(),
            _handler_cmd(scenario, "disarm-trap", trap_id=str(disarmed_trap.id)),
            "trap is already disarmed",
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


async def test_claim_base_place_and_disarm_trap():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    claimed: list[BaseClaimedEvent] = []
    placed: list[TrapPlacedEvent] = []
    disarmed: list[TrapDisarmedEvent] = []
    scenario.actor.bus.subscribe(BaseClaimedEvent, claimed.append)
    scenario.actor.bus.subscribe(TrapPlacedEvent, placed.append)
    scenario.actor.bus.subscribe(TrapDisarmedEvent, disarmed.append)

    await scenario.actor.submit(_cmd(scenario, "claim-base", clan="Moss Fangs"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "place-trap", damage=7.0))
    await scenario.actor.tick(HOUR)

    room = scenario.actor.world.get_entity(scenario.room_a)
    claim = room.get_component(BaseClaimComponent)
    trap_id = parse_entity_id(placed[0].trap_id)
    assert trap_id is not None
    trap = scenario.actor.world.get_entity(trap_id)
    assert claim.claimed_by == str(scenario.character)
    assert claimed[0].clan == "Moss Fangs"
    assert trap.get_component(TrapComponent).armed is True

    await scenario.actor.submit(_cmd(scenario, "disarm-trap", trap_id=str(trap_id)))
    await scenario.actor.tick(HOUR)

    assert trap.get_component(TrapComponent).armed is False
    assert disarmed[0].trap_id == str(trap_id)
    fragments = barbariansim_fragments(
        scenario.actor.world,
        scenario.actor.world.get_entity(scenario.character),
    )
    assert any("Base claim" in line and "Moss Fangs" in line for line in fragments)
    assert any("Trap armed trap: disarmed, 7 damage" in line for line in fragments)


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


def test_barbariansim_component_prompt_fragments_cover_self_and_target_context():
    scenario = build_scenario()
    world = scenario.actor.world
    master = world.get_entity(scenario.character)
    viewer = spawn_entity(world, [CharacterComponent()])
    thrall = spawn_entity(
        world,
        [
            IdentityComponent(name="Captive", kind="character"),
            CharacterComponent(),
            ThrallComponent(master_id=str(master.id), task="haul"),
        ],
    )
    weapon = spawn_entity(
        world,
        [
            WeaponComponent(damage=7, damage_type="axe"),
            DurabilityComponent(current=3, maximum=5),
        ],
    )
    self_ctx = ComponentPromptContext.for_entity(world, master)
    external_ctx = ComponentPromptContext.for_entity(
        world,
        master,
        perspective=PromptPerspective(viewer=viewer),
    )
    thrall_ctx = ComponentPromptContext.for_entity(
        world,
        thrall,
        perspective=self_ctx.perspective,
        target=master,
    )
    external_thrall_ctx = ComponentPromptContext.for_entity(
        world,
        thrall,
        perspective=external_ctx.perspective,
        target=master,
    )
    weapon_ctx = ComponentPromptContext.for_entity(world, weapon)

    assert StaminaComponent(current=4, maximum=10).prompt_fragments(self_ctx) == ("Stamina: 4/10.",)
    assert StaminaComponent(current=4, maximum=10).prompt_fragments(external_ctx) == ()
    assert thrall.get_component(ThrallComponent).prompt_fragments(thrall_ctx) == (
        "Your thrall Captive is set to haul.",
    )
    assert thrall.get_component(ThrallComponent).prompt_fragments(external_thrall_ctx) == ()
    assert weapon.get_component(WeaponComponent).prompt_fragments(weapon_ctx) == (
        "Reachable weapon: axe (7.0 damage, durability 3/5).",
    )


def test_generate_raid_spawn_specs_builds_swarm_with_few_leaders():
    specs = generate_raid_spawn_specs(12, "barbarian_raid:3600:12")

    assert all(isinstance(spec, RaiderSpawnSpec) for spec in specs)
    assert specs == generate_raid_spawn_specs(12, "barbarian_raid:3600:12")
    ranks = [spec.rank for spec in specs]
    assert ranks.count("raider") == 4
    assert ranks.count("officer") == 1
    assert ranks.count("warlord") == 1
    leaders = ranks.count("officer") + ranks.count("warlord")
    assert ranks.count("raider") > leaders
    raiders = [spec for spec in specs if spec.rank == "raider"]
    warlords = [spec for spec in specs if spec.rank == "warlord"]
    assert all(spec.armor == 0.0 and not spec.lethal_capable for spec in raiders)
    assert all(spec.lethal_capable and spec.armor > 0 for spec in warlords)
    # Even a tiny budget still fields at least one weak raider.
    assert any(spec.rank == "raider" for spec in generate_raid_spawn_specs(1, "tiny"))


def test_barbarian_raid_enrichment_is_seeded_and_idempotent():
    scenario = build_scenario()
    world = scenario.actor.world
    incident = spawn_entity(
        world,
        [
            IdentityComponent(name="barbarian raid", kind="incident"),
            IncidentComponent(kind="barbarian_raid", budget_spent=12, started_at_epoch=0),
        ],
    )
    enrichment = BarbarianRaidEnrichment(world)

    def event_for(
        target,
        *,
        kind: str = "barbarian_raid",
        incident_id: str | None = None,
        wants: tuple[str, ...] = ("raid-swarm",),
    ) -> IncidentGeneratedEvent:
        return IncidentGeneratedEvent(
            event_id="event",
            world_epoch=0,
            created_at=datetime.now(UTC),
            room_id=str(target.id),
            target_ids=(str(incident.id),),
            seed="raid-seed",
            incident_id=incident_id if incident_id is not None else str(incident.id),
            incident_key=kind,
            kind=kind,
            budget_spent=12,
            generation=GenerationIntentComponent(wants=wants),
        )

    # Unrelated incident kinds without the raid-swarm want are ignored.
    enrichment._on_incident(
        event_for(world.get_entity(scenario.room_a), kind="resource_drop", wants=())
    )
    assert incident.get_relationships(IncidentSpawned) == []

    # A missing incident id is ignored.
    enrichment._on_incident(event_for(world.get_entity(scenario.room_a), incident_id="not-an-id"))
    assert incident.get_relationships(IncidentSpawned) == []

    enrichment._on_incident(event_for(world.get_entity(scenario.room_a)))
    spawned = incident.get_relationships(IncidentSpawned)
    raiders = [world.get_entity(target_id) for _edge, target_id in spawned]
    assert len(raiders) == 6
    assert all(edge.kind == "monster" for edge, _target_id in spawned)
    assert all(raider.get_component(CharacterComponent).species == "raider" for raider in raiders)
    assert all(raider.has_component(WeaponComponent) for raider in raiders)
    assert {container_of(raider) for raider in raiders} == {scenario.room_a}

    # Re-running the enrichment does not double-spawn the swarm.
    enrichment._on_incident(event_for(world.get_entity(scenario.room_a)))
    assert incident.get_relationships(IncidentSpawned) == spawned


async def test_storyteller_selects_barbarian_raid_only_when_colonysim_and_barbariansim_enabled():
    scenario = build_scenario()
    install_barbariansim(scenario.actor)
    scenario.actor.register_consequence(
        StorytellerConsequence((*default_incident_definitions(), BARBARIAN_RAID))
    )
    spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="steady storyteller", kind="controller"),
            StorytellerComponent(interval_seconds=int(HOUR), next_incident_epoch=int(HOUR)),
            IncidentBudgetComponent(points=13.0, points_per_day=0.0),
        ],
    )

    await scenario.actor.tick(HOUR)

    incident = next(
        entity
        for entity in scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    assert incident.get_component(IncidentComponent).kind == "hostile_encounter"

    scenario = build_scenario()
    install_colonysim(scenario.actor)
    install_barbariansim(scenario.actor)
    scenario.actor.register_consequence(
        StorytellerConsequence((*default_incident_definitions(), BARBARIAN_RAID))
    )
    world = scenario.actor.world
    spawn_entity(
        world,
        [
            IdentityComponent(name="raid storyteller", kind="controller"),
            StorytellerComponent(interval_seconds=int(HOUR), next_incident_epoch=int(HOUR)),
            IncidentBudgetComponent(points=13.0, points_per_day=0.0),
        ],
    )

    await scenario.actor.tick(HOUR)

    incident = next(
        entity for entity in world.query().with_all([IncidentComponent]).execute_entities()
    )
    assert incident.get_component(IncidentComponent).kind == "barbarian_raid"
    spawned = incident.get_relationships(IncidentSpawned)
    raiders = [world.get_entity(target_id) for _edge, target_id in spawned]
    assert raiders
    assert all(raider.get_component(CharacterComponent).species == "raider" for raider in raiders)
    ranks = [raider.get_component(IdentityComponent).tags[-1] for raider in raiders]
    assert "warlord" in ranks
    assert ranks.count("raider") > ranks.count("warlord")
    assert {container_of(raider) for raider in raiders} == {scenario.room_a}


def _downed_target(scenario, **kwargs):
    target = _target(scenario, **kwargs)
    scenario.actor.world.get_entity(target).add_component(
        DownedComponent(downed_at_epoch=0, cause="combat")
    )
    return target


async def test_subdue_binds_a_defeated_target_as_a_thrall():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _downed_target(scenario)
    taken: list[ThrallTakenEvent] = []
    scenario.actor.bus.subscribe(ThrallTakenEvent, taken.append)

    await scenario.actor.submit(_cmd(scenario, "subdue", target_id=str(target), task="haul"))
    await scenario.actor.tick(HOUR)

    thrall = scenario.actor.world.get_entity(target).get_component(ThrallComponent)
    assert thrall.master_id == str(scenario.character)
    assert thrall.task == "haul"
    assert taken and taken[0].thrall_id == str(target)


def test_subdue_requires_a_defeated_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    standing = _target(scenario)

    result = SubdueHandler().execute(ctx, _handler_cmd(scenario, "subdue", target_id=str(standing)))

    assert not result.ok
    assert "defeated" in result.reason
    assert not scenario.actor.world.get_entity(standing).has_component(ThrallComponent)


async def test_recruit_follower_then_command_and_release():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _target(scenario)
    recruited: list[FollowerRecruitedEvent] = []
    ordered: list[FollowerOrderChangedEvent] = []
    released: list[ThrallReleasedEvent] = []
    scenario.actor.bus.subscribe(FollowerRecruitedEvent, recruited.append)
    scenario.actor.bus.subscribe(FollowerOrderChangedEvent, ordered.append)
    scenario.actor.bus.subscribe(ThrallReleasedEvent, released.append)

    await scenario.actor.submit(_cmd(scenario, "recruit-follower", target_id=str(target)))
    await scenario.actor.tick(HOUR)
    follower = scenario.actor.world.get_entity(target).get_component(FollowerComponent)
    assert follower.master_id == str(scenario.character)
    assert recruited

    await scenario.actor.submit(
        _cmd(scenario, "command", target_id=str(target), instruction="guard the burrow")
    )
    await scenario.actor.tick(HOUR)
    assert (
        scenario.actor.world.get_entity(target).get_component(FollowerComponent).orders
        == "guard the burrow"
    )
    assert ordered and ordered[0].orders == "guard the burrow"

    await scenario.actor.submit(_cmd(scenario, "release-thrall", target_id=str(target)))
    await scenario.actor.tick(HOUR)
    assert not scenario.actor.world.get_entity(target).has_component(FollowerComponent)
    assert released


def test_command_follower_rejects_non_master():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = _target(scenario)
    scenario.actor.world.get_entity(target).add_component(
        FollowerComponent(master_id="some-other-master")
    )

    result = CommandFollowerHandler().execute(
        ctx, _handler_cmd(scenario, "command", target_id=str(target), instruction="follow")
    )

    assert not result.ok
    assert "command" in result.reason


async def test_fragments_describe_thrall_and_follower_state():
    scenario = build_scenario()
    _install(scenario.actor)
    thrall = _downed_target(scenario)
    await scenario.actor.submit(_cmd(scenario, "subdue", target_id=str(thrall), task="haul"))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    master = world.get_entity(scenario.character)
    master_lines = barbariansim_fragments(world, master)
    assert any("thrall" in line and "haul" in line for line in master_lines)

    thrall_lines = barbariansim_fragments(world, world.get_entity(thrall))
    assert any("bound as a thrall" in line for line in thrall_lines)


def test_thrall_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    standing = _target(scenario)
    downed = _downed_target(scenario)
    dead_downed = _downed_target(scenario)
    world.get_entity(dead_downed).add_component(DeadComponent(died_at_epoch=0, cause="test"))
    bound = _downed_target(scenario)
    world.get_entity(bound).add_component(ThrallComponent(master_id="someone-else"))
    served = _target(scenario)
    world.get_entity(served).add_component(FollowerComponent(master_id="someone-else"))
    distant = _downed_target(scenario)
    # move the distant captive into room_b so it is not present
    world.get_entity(scenario.room_a).remove_relationship(Contains, distant)
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant
    )
    rock = spawn_entity(world, [IdentityComponent(name="rock", kind="item")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rock.id
    )

    me = str(scenario.character)

    def case(handler, expected, **payload):
        return handler, expected, payload

    cases = [
        case(SubdueHandler(), "invalid captor", character_id="x"),
        case(SubdueHandler(), "cannot subdue yourself", target_id=me),
        case(SubdueHandler(), "does not exist", target_id="ghost_999999"),
        case(SubdueHandler(), "cannot be bound", target_id=str(rock.id)),
        case(SubdueHandler(), "is dead", target_id=str(dead_downed)),
        case(SubdueHandler(), "already serves", target_id=str(bound)),
        case(SubdueHandler(), "not present", target_id=str(distant)),
        case(RecruitFollowerHandler(), "invalid leader", character_id="x"),
        case(RecruitFollowerHandler(), "cannot recruit yourself", target_id=me),
        case(RecruitFollowerHandler(), "cannot be recruited", target_id=str(rock.id)),
        case(RecruitFollowerHandler(), "cannot be recruited in this state", target_id=str(downed)),
        case(RecruitFollowerHandler(), "already serves", target_id=str(served)),
        case(CommandFollowerHandler(), "invalid master", character_id="x"),
        case(CommandFollowerHandler(), "orders must not be empty", target_id=str(standing)),
        case(
            CommandFollowerHandler(),
            "does not exist",
            target_id="ghost_999999",
            instruction="go",
        ),
        case(ReleaseThrallHandler(), "invalid master", character_id="x"),
        case(ReleaseThrallHandler(), "does not exist", target_id="ghost_999999"),
        case(ReleaseThrallHandler(), "do not command", target_id=str(bound)),
    ]
    for handler, expected, payload in cases:
        result = handler.execute(ctx, _handler_cmd(scenario, handler.command_type, **payload))
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


async def test_thrall_task_can_be_reassigned_and_released():
    scenario = build_scenario()
    _install(scenario.actor)
    thrall = _downed_target(scenario)
    await scenario.actor.submit(_cmd(scenario, "subdue", target_id=str(thrall)))
    await scenario.actor.tick(HOUR)

    await scenario.actor.submit(
        _cmd(scenario, "command", target_id=str(thrall), instruction="cook")
    )
    await scenario.actor.tick(HOUR)
    assert scenario.actor.world.get_entity(thrall).get_component(ThrallComponent).task == "cook"

    await scenario.actor.submit(_cmd(scenario, "release-thrall", target_id=str(thrall)))
    await scenario.actor.tick(HOUR)
    assert not scenario.actor.world.get_entity(thrall).has_component(ThrallComponent)


async def test_fragments_list_a_recruited_follower_for_the_master():
    scenario = build_scenario()
    _install(scenario.actor)
    follower = _target(scenario)
    await scenario.actor.submit(_cmd(scenario, "recruit-follower", target_id=str(follower)))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    master_lines = barbariansim_fragments(world, world.get_entity(scenario.character))
    assert any("follower" in line and "follow" in line for line in master_lines)
    follower_lines = barbariansim_fragments(world, world.get_entity(follower))
    assert any("follow a leader" in line for line in follower_lines)


def test_status_component_fragments_are_hidden_from_external_viewers():
    scenario = build_scenario()
    world = scenario.actor.world
    owner = world.get_entity(scenario.character)
    viewer = spawn_entity(world, [CharacterComponent()])
    self_ctx = ComponentPromptContext.for_entity(world, owner)
    external_ctx = ComponentPromptContext.for_entity(
        world, owner, perspective=PromptPerspective(viewer=viewer)
    )

    # Components whose self-view emits a line but whose external-view is empty.
    exposure = TemperatureExposureComponent(heat=4.0, cold=2.0, heat_danger=True, cold_danger=True)
    self_exposure = exposure.prompt_fragments(self_ctx)
    assert "Exposure: heat 4, cold 2." in self_exposure
    assert "You are suffering dangerous heat exposure." in self_exposure
    assert "You are suffering dangerous cold exposure." in self_exposure
    assert exposure.prompt_fragments(external_ctx) == ()

    assert PoisonComponent(severity=2.0).prompt_fragments(self_ctx) == ("Poisoned: severity 2.",)
    assert PoisonComponent(severity=2.0).prompt_fragments(external_ctx) == ()

    assert CorruptionComponent(amount=3.0).prompt_fragments(self_ctx) == ("Corruption: 3.",)
    assert CorruptionComponent(amount=3.0).prompt_fragments(external_ctx) == ()

    assert ArmorComponent(rating=2.0).prompt_fragments(self_ctx) == ("Your armor rating is 2.0.",)
    assert ArmorComponent(rating=2.0).prompt_fragments(external_ctx) == ()

    assert DefendingComponent(started_at_epoch=0).prompt_fragments(self_ctx) == (
        "You are defending yourself.",
    )
    assert DefendingComponent(started_at_epoch=0).prompt_fragments(external_ctx) == ()

    assert BlessingComponent(name="ember").prompt_fragments(self_ctx) == ("Blessing: ember.",)
    assert BlessingComponent(name="ember").prompt_fragments(external_ctx) == ()

    assert CurseComponent(name="ash").prompt_fragments(self_ctx) == ("Curse: ash severity 1.",)
    assert CurseComponent(name="ash").prompt_fragments(external_ctx) == ()

    assert ClimbingSkillComponent(level=3).prompt_fragments(self_ctx) == ("Climbing skill: 3.",)
    assert ClimbingSkillComponent(level=3).prompt_fragments(external_ctx) == ()


def test_follower_fragment_is_empty_for_unrelated_external_viewer():
    scenario = build_scenario()
    world = scenario.actor.world
    master = world.get_entity(scenario.character)
    bystander = spawn_entity(world, [CharacterComponent()])
    follower = spawn_entity(
        world,
        [
            IdentityComponent(name="Recruit", kind="character"),
            CharacterComponent(),
            FollowerComponent(master_id=str(master.id), orders="scout"),
        ],
    )
    # External viewer who is not the master, with the follower as the subject.
    external_ctx = ComponentPromptContext.for_entity(
        world,
        follower,
        perspective=PromptPerspective(viewer=bystander),
        target=master,
    )
    assert follower.get_component(FollowerComponent).prompt_fragments(external_ctx) == ()


def test_weapon_fragment_without_durability_omits_durability_clause():
    scenario = build_scenario()
    world = scenario.actor.world
    weapon = spawn_entity(world, [WeaponComponent(damage=5, damage_type="club")])
    weapon_ctx = ComponentPromptContext.for_entity(world, weapon)
    assert weapon.get_component(WeaponComponent).prompt_fragments(weapon_ctx) == (
        "Reachable weapon: club (5.0 damage).",
    )


def test_attack_uses_requested_body_part_string():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = _target(scenario, health=20.0)
    _weapon(scenario, damage=6.0)
    result = AttackHandler().execute(
        ctx,
        _handler_cmd(scenario, "attack", target_id=str(target), body_part="left arm"),
    )
    assert result.ok, result.reason
    injuries = [e for e in result.events if e.__class__.__name__ == "InjuryAddedEvent"]
    assert injuries and injuries[0].body_part == "left arm"


def test_attack_defaults_to_body_when_body_plan_has_no_parts():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = _target(scenario, health=20.0)
    # A body plan present but with no parts falls back to the generic "body".
    scenario.actor.world.get_entity(target).add_component(BodyPlanComponent(parts=()))
    _weapon(scenario, damage=6.0)
    result = AttackHandler().execute(ctx, _handler_cmd(scenario, "attack", target_id=str(target)))
    assert result.ok, result.reason
    injuries = [e for e in result.events if e.__class__.__name__ == "InjuryAddedEvent"]
    assert injuries and injuries[0].body_part == "body"


def test_place_trap_rejects_when_character_has_no_room():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # A homeless character entity with no containing room.
    loose = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Drifter", kind="character"), CharacterComponent()],
    )
    result = PlaceTrapHandler().execute(
        ctx,
        _handler_cmd(scenario, "place-trap", character_id=str(loose.id)),
    )
    assert not result.ok
    assert result.reason == "no room to place trap"


def test_defend_rejects_when_stamina_is_insufficient():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(StaminaComponent(current=0.0, maximum=10.0))
    result = DefendHandler().execute(ctx, _handler_cmd(scenario, "defend"))
    assert not result.ok
    assert "stamina" in (result.reason or "")


def test_recruit_follower_rejects_nonexistent_target():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = RecruitFollowerHandler().execute(
        ctx,
        _handler_cmd(scenario, "recruit-follower", target_id="entity_999999"),
    )
    assert not result.ok
    assert result.reason == "target does not exist"


def test_recruit_follower_rejects_target_in_another_room():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    distant = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Far One", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), distant.id
    )
    result = RecruitFollowerHandler().execute(
        ctx,
        _handler_cmd(scenario, "recruit-follower", target_id=str(distant.id)),
    )
    assert not result.ok
    assert result.reason == "target is not present"


def test_perform_ritual_without_blessing_curse_or_corruption():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    shrine = _room_entity(scenario, "plain shrine", "shrine", [ShrineComponent()])
    ritual = _room_entity(
        scenario,
        "silent rite",
        "ritual",
        [RitualComponent(blessing="", curse="", corruption_cost=0.0)],
    )
    result = PerformRitualHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "perform-ritual",
            shrine_id=str(shrine.id),
            ritual_id=str(ritual.id),
        ),
    )
    assert result.ok, result.reason
    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(BlessingComponent)
    assert not character.has_component(CurseComponent)
    assert not character.has_component(CorruptionComponent)


def test_parity_handlers_reject_targets_in_another_room():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room_b = scenario.actor.world.get_entity(scenario.room_b)

    def _in_room_b(name, kind, components):
        entity = spawn_entity(
            scenario.actor.world,
            [IdentityComponent(name=name, kind=kind), *components],
        )
        room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
        return entity

    building = _in_room_b(
        "far wall", "building", [BuildingComponent(integrity=8.0, maximum_integrity=10.0)]
    )
    base = _in_room_b("far camp", "base", [])
    treasure = _in_room_b("far hoard", "treasure", [TreasureComponent(treasure_type="hoard")])

    cases = [
        (
            UpgradeBuildingHandler(),
            "upgrade-building",
            {"building_id": str(building.id), "integrity": 2},
            "building is not reachable",
        ),
        (
            DemolishBuildingHandler(),
            "demolish-building",
            {"building_id": str(building.id)},
            "building is not reachable",
        ),
        (
            PrepareSiegeHandler(),
            "prepare-siege",
            {"base_id": str(base.id), "score": 2},
            "base is not reachable",
        ),
        (
            StartPurgeWaveHandler(),
            "start-purge-wave",
            {"base_id": str(base.id)},
            "base is not reachable",
        ),
        (
            UnlockTreasureHandler(),
            "unlock-treasure",
            {"treasure_id": str(treasure.id)},
            "treasure is not reachable",
        ),
        (
            ClaimTreasureHandler(),
            "claim-treasure",
            {"treasure_id": str(treasure.id)},
            "treasure is not reachable",
        ),
    ]
    for handler, command_type, payload, reason in cases:
        result = handler.execute(ctx, _handler_cmd(scenario, command_type, **payload))
        assert not result.ok, command_type
        assert result.reason == reason, command_type


def test_unlock_treasure_with_locked_key_requirement_and_wrong_key():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    treasure = _room_entity(
        scenario,
        "keyed hoard",
        "treasure",
        [TreasureComponent(treasure_type="hoard", key_name="ruby")],
    )
    # No key carried at all.
    no_key = UnlockTreasureHandler().execute(
        ctx, _handler_cmd(scenario, "unlock-treasure", treasure_id=str(treasure.id))
    )
    assert not no_key.ok
    assert no_key.reason == "required key is not carried"

    # Carry a key with the wrong name.
    wrong = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="brass key", kind="key"),
            PortableComponent(can_pick_up=True),
            KeyComponent(key_name="brass"),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), wrong.id)
    wrong_key = UnlockTreasureHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "unlock-treasure",
            treasure_id=str(treasure.id),
            key_id=str(wrong.id),
        ),
    )
    assert not wrong_key.ok
    assert wrong_key.reason == "wrong key"


async def test_temperature_exposure_skips_when_no_time_has_elapsed():
    scenario = build_scenario()
    _install(scenario.actor)
    await scenario.actor.tick(HOUR)
    epoch = scenario.actor.epoch
    character = scenario.actor.world.get_entity(scenario.character)
    # last_updated_epoch in the future relative to the next tick -> elapsed <= 0.
    character.add_component(
        TemperatureExposureComponent(heat=5.0, last_updated_epoch=epoch + 10_000_000)
    )
    await scenario.actor.tick(HOUR)
    exposure = character.get_component(TemperatureExposureComponent)
    assert exposure.heat == 5.0


def test_damage_item_noop_when_item_is_already_broken():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    weapon = _durable_weapon(scenario, durability=1.0)
    replace_component(
        scenario.actor.world.get_entity(weapon),
        DurabilityComponent(current=0.0, maximum=1.0, broken=True),
    )
    target = _target(scenario)
    result = AttackHandler().execute(ctx, _handler_cmd(scenario, "attack", target_id=str(target)))
    assert result.ok, result.reason
    # An already-broken weapon emits no further item damage/break events.
    assert not any(
        e.__class__.__name__ in {"ItemDamagedEvent", "ItemBrokenEvent"} for e in result.events
    )


def test_exposure_fragments_cover_each_danger_independently():
    scenario = build_scenario()
    world = scenario.actor.world
    owner = world.get_entity(scenario.character)
    self_ctx = ComponentPromptContext.for_entity(world, owner)

    # No exposure values but cold is dangerous: skips the exposure summary and
    # the heat-danger line, emitting only the cold-danger warning.
    cold_only = TemperatureExposureComponent(cold_danger=True)
    assert cold_only.prompt_fragments(self_ctx) == ("You are suffering dangerous cold exposure.",)

    # Heat danger without cold danger emits only the heat-danger warning.
    heat_only = TemperatureExposureComponent(heat_danger=True)
    assert heat_only.prompt_fragments(self_ctx) == ("You are suffering dangerous heat exposure.",)


def test_armor_rating_ignores_worn_items_without_armor_component():
    scenario = build_scenario()
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    target = _target(scenario, health=20.0, armor=2.0)
    # A worn item with no ArmorComponent must not change the armor rating.
    cloak = spawn_entity(
        world,
        [IdentityComponent(name="plain cloak", kind="armor"), PortableComponent()],
    )
    target_entity = world.get_entity(target)
    target_entity.add_relationship(Contains(mode=ContainmentMode.INVENTORY), cloak.id)
    target_entity.add_relationship(Wearing(slot="torso"), cloak.id)

    assert armor_rating(ctx, target) == 2.0


def test_ambient_celsius_is_none_without_temperature_component():
    scenario = build_scenario()
    world = scenario.actor.world
    # The starting room carries no TemperatureComponent.
    assert ambient_celsius(world, scenario.room_a) is None


def test_damage_item_skips_already_broken_item():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    weapon = _durable_weapon(scenario, durability=1.0)
    replace_component(
        scenario.actor.world.get_entity(weapon),
        DurabilityComponent(current=0.0, maximum=1.0, broken=True),
    )

    events = damage_item(ctx, weapon, amount=1.0, actor_id=scenario.character)

    # A broken item yields no events and its durability is untouched.
    assert events == []
    durability = scenario.actor.world.get_entity(weapon).get_component(DurabilityComponent)
    assert durability.broken is True
    assert durability.current == 0.0


def test_damage_item_without_breaking_emits_only_a_damage_event():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    weapon = _durable_weapon(scenario, durability=5.0)

    events = damage_item(ctx, weapon, amount=2.0, actor_id=scenario.character)

    # Durability stays above zero, so only a damage event (no break) is emitted.
    assert [e.__class__.__name__ for e in events] == ["ItemDamagedEvent"]
    assert events[0].durability == 3.0
    durability = scenario.actor.world.get_entity(weapon).get_component(DurabilityComponent)
    assert durability.broken is False
    assert durability.current == 3.0


async def test_attack_fully_absorbed_by_armor_inflicts_no_injury():
    scenario = build_scenario()
    _install(scenario.actor)
    # Armor outweighs the weapon, so damage clamps to zero and no injury is made.
    target = _target(scenario, health=20.0, armor=10.0)
    weapon = _weapon(scenario, damage=4.0)

    result = AttackHandler().execute(
        HandlerContext(scenario.actor.world, scenario.actor.epoch),
        _handler_cmd(scenario, "attack", target_id=str(target), weapon_id=str(weapon)),
    )

    assert result.ok, result.reason
    # Zero damage: the attack still lands but no injury entity is spawned.
    assert not any(e.__class__.__name__ == "InjuryAddedEvent" for e in result.events)
    target_entity = scenario.actor.world.get_entity(target)
    assert target_entity.get_component(HealthComponent).current == 20.0
    assert not target_entity.get_relationships(HasInjury)


async def test_raid_with_depleted_fortification_does_not_replace_component():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    target = _room_entity(
        scenario,
        "cracked wall",
        "fortification",
        [FortificationComponent(rating=1.0, durability=0.0)],
    )
    raids: list[RaidStartedEvent] = []
    scenario.actor.bus.subscribe(RaidStartedEvent, raids.append)

    result = RaidHandler().execute(
        ctx, _handler_cmd(scenario, "raid", target_id=str(target.id), intensity=5.0)
    )

    assert result.ok, result.reason
    # Durability already at zero: the component is left exactly as-is.
    fortification = target.get_component(FortificationComponent)
    assert fortification.durability == 0.0
    assert fortification.rating == 1.0


async def test_prepare_siege_defaults_to_current_room():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    result = PrepareSiegeHandler().execute(ctx, _handler_cmd(scenario, "prepare-siege", score=3.0))

    assert result.ok, result.reason
    room = scenario.actor.world.get_entity(scenario.room_a)
    assert room.get_component(SiegeReadinessComponent).score == 3.0


async def test_start_purge_wave_defaults_to_current_room():
    scenario = build_scenario()
    _install(scenario.actor, enabled=frozenset())
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    result = StartPurgeWaveHandler().execute(
        ctx, _handler_cmd(scenario, "start-purge-wave", intensity=2.0)
    )

    assert result.ok, result.reason
    room = scenario.actor.world.get_entity(scenario.room_a)
    assert room.get_component(PurgeWaveComponent).active is True


def test_unlock_treasure_without_key_requirement_needs_no_key():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    treasure = _room_entity(
        scenario,
        "open hoard",
        "treasure",
        [TreasureComponent(treasure_type="hoard", key_name="")],
    )

    result = UnlockTreasureHandler().execute(
        ctx, _handler_cmd(scenario, "unlock-treasure", treasure_id=str(treasure.id))
    )

    assert result.ok, result.reason
    assert treasure.get_component(TreasureComponent).locked is False


def test_ensure_barbariansim_policy_returns_existing_singleton():
    scenario = build_scenario()
    _install(scenario.actor)
    # install_barbariansim already spawned the policy; a second call must reuse it.
    before = list(
        scenario.actor.world.query().with_all([BarbarianSimPolicyComponent]).execute_entities()
    )
    assert len(before) == 1

    policy = ensure_barbariansim_policy(scenario.actor)

    assert isinstance(policy, BarbarianSimPolicyComponent)
    after = list(
        scenario.actor.world.query().with_all([BarbarianSimPolicyComponent]).execute_entities()
    )
    assert len(after) == 1
