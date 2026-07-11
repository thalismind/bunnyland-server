"""Tests for dragon-sim discovery, quests, and factions."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    IdentityComponent,
    Lane,
    PortableComponent,
    ReadableComponent,
    SleepingComponent,
    WritableComponent,
    build_submitted_command,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.prompts import ComponentPromptContext, PromptPerspective
from bunnyland.simpacks.dragonsim.mechanics import (
    AbsorbGreatSoulHandler,
    AcceptQuestHandler,
    AncientBeastComponent,
    AppeaseAncientBeastHandler,
    ArtifactComponent,
    ArtifactIdentifiedEvent,
    ArtifactUsedEvent,
    BountyPaidEvent,
    BrewPotionHandler,
    BribeGuardHandler,
    CarvableComponent,
    CastDragonSpellHandler,
    ChangeFactionRankHandler,
    ChooseQuestBranchHandler,
    CompleteObjectiveHandler,
    CrimeReportedEvent,
    CrimeWitnessedEvent,
    DeclineQuestHandler,
    DependsOnIngredient,
    DiscoverLocationHandler,
    DiscoveryComponent,
    DragonSpellCastEvent,
    EncounterTriggeredEvent,
    EncounterZoneComponent,
    FactionComponent,
    FactionJoinedEvent,
    FactionLeftEvent,
    FactionRankChangedEvent,
    GreatSoulAbsorbedEvent,
    GreatSoulComponent,
    GuardBribedEvent,
    GuardComponent,
    HasPerk,
    IdentifyArtifactHandler,
    InscribeVoicePhraseHandler,
    JailComponent,
    JailSentenceServedEvent,
    JoinFactionHandler,
    KnowsSpell,
    KnowsWord,
    LearnSpellHandler,
    LearnWordOfPowerHandler,
    LeaveFactionHandler,
    LocationDiscoveredEvent,
    LockDifficultyComponent,
    LockPickedEvent,
    LoreBookComponent,
    LoreBookReadEvent,
    MagicComponent,
    MagicRecoveredEvent,
    MapMarkerAddedEvent,
    MapMarkerComponent,
    MarkMapHandler,
    MemberOfFaction,
    PayBountyHandler,
    PerkComponent,
    PerkUnlockedEvent,
    PersuadeHandler,
    PersuasionAttemptedEvent,
    PersuasionComponent,
    PickLockHandler,
    PointOfInterestComponent,
    PotionBrewedEvent,
    PotionComponent,
    PotionRecipeComponent,
    QuestAcceptedBy,
    QuestAcceptedEvent,
    QuestBranchChosenEvent,
    QuestCompletedEvent,
    QuestComponent,
    QuestDeclinedEvent,
    QuestHasObjective,
    QuestHasReward,
    QuestObjectiveCompletedEvent,
    QuestObjectiveComponent,
    QuestRewardComponent,
    QuestRewardGrants,
    QuestStateComponent,
    QuestTrackedEvent,
    ReadLoreBookHandler,
    RecoverMagicHandler,
    ReportCrimeHandler,
    ServeJailTimeHandler,
    SneakHandler,
    SneakingComponent,
    SpeakWordOfPowerHandler,
    SpellComponent,
    SpellCooldownComponent,
    SpellLearnedEvent,
    StealHandler,
    StealthChangedEvent,
    StudyVoiceInscriptionHandler,
    SurrenderComponent,
    SurrenderedEvent,
    SurrenderHandler,
    TheftCommittedEvent,
    TrackQuestHandler,
    TracksQuest,
    TriggerEncounterHandler,
    UnlockPerkHandler,
    UseArtifactHandler,
    VoiceInscriptionComponent,
    VoiceInscriptionStudiedEvent,
    VoicePhraseInscribedEvent,
    WantedComponent,
    WordOfPowerComponent,
    WordOfPowerLearnedEvent,
    WordOfPowerSpokenEvent,
    dragonsim_fragments,
)
from bunnyland.simpacks.lifesim.mechanics import SkillSetComponent

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(DiscoverLocationHandler())
    actor.register_handler(MarkMapHandler())
    actor.register_handler(TriggerEncounterHandler())
    actor.register_handler(AcceptQuestHandler())
    actor.register_handler(CompleteObjectiveHandler())
    actor.register_handler(UnlockPerkHandler())
    actor.register_handler(AbsorbGreatSoulHandler())
    actor.register_handler(LearnWordOfPowerHandler())
    actor.register_handler(SpeakWordOfPowerHandler())
    actor.register_handler(JoinFactionHandler())
    actor.register_handler(LeaveFactionHandler())
    actor.register_handler(ChangeFactionRankHandler())
    actor.register_handler(SneakHandler())
    actor.register_handler(StealHandler())
    actor.register_handler(PayBountyHandler())
    actor.register_handler(BribeGuardHandler())
    actor.register_handler(ServeJailTimeHandler())
    actor.register_handler(PickLockHandler())
    actor.register_handler(ReadLoreBookHandler())
    actor.register_handler(LearnSpellHandler())
    actor.register_handler(CastDragonSpellHandler())
    actor.register_handler(BrewPotionHandler())
    actor.register_handler(UseArtifactHandler())
    actor.register_handler(InscribeVoicePhraseHandler())
    actor.register_handler(StudyVoiceInscriptionHandler())


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


def _dragon_room_entity(scenario, name, kind, components):
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), *components],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


def _poi(scenario):
    poi = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="old watchtower", kind="location"),
            PointOfInterestComponent(location_type="ruin", region="north meadow"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), poi.id
    )
    return poi.id


def test_dragonsim_parity_handlers_mutate_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MagicComponent(current=1, maximum=10, regen_per_hour=3))

    accepted_quest = _dragon_room_entity(
        scenario,
        "Find the Lost Ring",
        "quest",
        [
            QuestComponent(
                quest_id="lost-ring",
                title="Find the Lost Ring",
            ),
            QuestStateComponent(status="active"),
        ],
    )
    declined_quest = _dragon_room_entity(
        scenario,
        "Wolf Road Trouble",
        "quest",
        [QuestComponent(quest_id="wolf-road", title="Wolf Road Trouble")],
    )
    declined_quest.add_component(QuestStateComponent())
    accepted_quest.add_relationship(QuestAcceptedBy(), scenario.character)
    target = _dragon_room_entity(
        scenario,
        "Moss Guard",
        "character",
        [CharacterComponent(species="bunny")],
    )
    criminal = _dragon_room_entity(
        scenario,
        "Bandit",
        "character",
        [CharacterComponent(species="bunny")],
    )
    faction = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Moss Wardens", kind="faction"), FactionComponent(name="Moss")],
    )
    artifact = _dragon_room_entity(
        scenario,
        "star mirror",
        "artifact",
        [ArtifactComponent(name="star mirror", charges=1)],
    )
    beast = _dragon_room_entity(
        scenario,
        "Ancient Wyrm",
        "beast",
        [AncientBeastComponent(name="Ancient Wyrm")],
    )

    calls = [
        (
            TrackQuestHandler(),
            "track-quest",
            {"quest_id": "lost-ring"},
            QuestTrackedEvent,
        ),
        (
            ChooseQuestBranchHandler(),
            "choose-quest-branch",
            {"quest_id": "lost-ring", "branch": "return"},
            QuestBranchChosenEvent,
        ),
        (
            DeclineQuestHandler(),
            "decline-quest",
            {"quest_id": "wolf-road"},
            QuestDeclinedEvent,
        ),
        (
            PersuadeHandler(),
            "persuade",
            {"target_id": str(target.id), "amount": 2},
            PersuasionAttemptedEvent,
        ),
        (
            SurrenderHandler(),
            "surrender",
            {"target_id": str(target.id), "reason": "fine"},
            SurrenderedEvent,
        ),
        (
            ReportCrimeHandler(),
            "report-crime",
            {
                "criminal_id": str(criminal.id),
                "faction_id": str(faction.id),
                "bounty": 7,
            },
            CrimeReportedEvent,
        ),
        (
            RecoverMagicHandler(),
            "recover-magic",
            {"amount": 3},
            MagicRecoveredEvent,
        ),
        (
            IdentifyArtifactHandler(),
            "identify",
            {"artifact_id": str(artifact.id)},
            ArtifactIdentifiedEvent,
        ),
        (
            AppeaseAncientBeastHandler(),
            "appease-ancient-beast",
            {"beast_id": str(beast.id), "method": "parley"},
            None,
        ),
    ]

    for handler, command_type, payload, event_type in calls:
        result = handler.execute(ctx, _handler_cmd(scenario, command_type, **payload))
        assert result.ok, (command_type, result.reason)
        if event_type is not None:
            assert any(isinstance(event, event_type) for event in result.events)

    assert (
        TrackQuestHandler()
        .execute(ctx, _handler_cmd(scenario, "track-quest", quest_id="lost-ring"))
        .ok
    )

    stage = accepted_quest.get_component(QuestStateComponent)
    assert character.has_relationship(TracksQuest, accepted_quest.id)
    assert stage.branch == "return"
    assert declined_quest.get_component(QuestStateComponent).status == "declined"
    assert target.get_component(PersuasionComponent).disposition == 2
    assert character.get_component(SurrenderComponent).reason == "fine"
    assert criminal.get_component(WantedComponent).amounts[str(faction.id)] == 7
    assert character.get_component(MagicComponent).current == 4
    assert str(scenario.character) in artifact.get_component(ArtifactComponent).identified_by
    fragments = dragonsim_fragments(scenario.actor.world, character)
    assert "Declined quest: Wolf Road Trouble." in fragments
    assert "Tracked quest stage 0, branch return." in fragments
    assert "Magic: 4/10." in fragments
    assert f"Surrendered to {target.id}." in fragments
    assert "Artifact nearby: star mirror (1 charges, identified)." in fragments
    assert "Moss Guard disposition: 2." in fragments


def test_dragonsim_parity_handlers_reject_invalid_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    fake = "entity_999999"
    cases = [
        (
            TrackQuestHandler(),
            "track-quest",
            {"quest_id": "missing"},
            "invalid character or quest id",
            "quest does not exist",
        ),
        (
            DeclineQuestHandler(),
            "decline-quest",
            {"quest_id": "missing"},
            "invalid character or quest id",
            "quest does not exist",
        ),
        (
            ChooseQuestBranchHandler(),
            "choose-quest-branch",
            {"quest_id": "missing", "branch": "left"},
            "invalid character, quest, or branch",
            "quest does not exist",
        ),
        (
            PersuadeHandler(),
            "persuade",
            {"target_id": fake},
            "invalid character or target id",
            "target does not exist",
        ),
        (
            SurrenderHandler(),
            "surrender",
            {"target_id": fake},
            "invalid character id",
            "target does not exist",
        ),
        (
            ReportCrimeHandler(),
            "report-crime",
            {"criminal_id": fake, "faction_id": fake},
            "invalid reporter, criminal, or faction id",
            "criminal or faction does not exist",
        ),
        (
            IdentifyArtifactHandler(),
            "identify",
            {"artifact_id": fake},
            "invalid character or artifact id",
            "artifact does not exist",
        ),
        (
            AppeaseAncientBeastHandler(),
            "appease-ancient-beast",
            {"beast_id": fake},
            "invalid character or beast id",
            "ancient beast does not exist",
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

    result = RecoverMagicHandler().execute(
        ctx,
        _handler_cmd(scenario, "recover-magic", character_id="not-an-id"),
    )
    assert result.ok is False
    assert result.reason == "invalid character id"


def test_dragonsim_location_handlers_reject_missing_character_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    poi_id = _poi(scenario)
    zone = _dragon_room_entity(
        scenario,
        "wolf road",
        "encounter-zone",
        [EncounterZoneComponent(zone_type="roadside")],
    )
    missing_character = "entity_999999"
    cases = [
        (DiscoverLocationHandler(), "discover-location", {"location_id": str(poi_id)}),
        (MarkMapHandler(), "mark-map", {"location_id": str(poi_id)}),
        (TriggerEncounterHandler(), "trigger-encounter", {"zone_id": str(zone.id)}),
    ]

    for handler, command_type, payload in cases:
        result = handler.execute(
            ctx,
            _handler_cmd(
                scenario,
                command_type,
                character_id=missing_character,
                **payload,
            ),
        )
        assert result.ok is False
        assert result.reason == "character does not exist"


def test_dragonsim_adventure_parity_handlers_reject_wrong_kind_and_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    wrong_kind = spawn_entity(world, [IdentityComponent(name="plain stone", kind="prop")])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    distant_npc = spawn_entity(
        world,
        [IdentityComponent(name="distant guard", kind="character"), CharacterComponent()],
    )
    faction = _faction(scenario)

    character.add_relationship(KnowsSpell(learned_at_epoch=0), wrong_kind.id)
    cooldown_spell = spawn_entity(
        world,
        [
            IdentityComponent(name="Slow Spark", kind="spell"),
            SpellComponent(name="Slow Spark", magic_cost=1),
            SpellCooldownComponent(cooldown_seconds=10, ready_at_epoch=ctx.epoch + 10),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), cooldown_spell.id)
    character.add_relationship(KnowsSpell(learned_at_epoch=0), cooldown_spell.id)
    expensive_spell = spawn_entity(
        world,
        [
            IdentityComponent(name="Meteor", kind="spell"),
            SpellComponent(name="Meteor", magic_cost=5, skill_name=""),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), expensive_spell.id)
    character.add_relationship(KnowsSpell(learned_at_epoch=0), expensive_spell.id)
    character.add_component(MagicComponent(current=0, maximum=5))

    locked_chest = spawn_entity(
        world,
        [
            IdentityComponent(name="open chest", kind="container"),
            LockDifficultyComponent(locked=False),
        ],
    )
    hard_lock = spawn_entity(
        world,
        [
            IdentityComponent(name="hard chest", kind="container"),
            LockDifficultyComponent(difficulty=3),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), locked_chest.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hard_lock.id)
    skill_spell = spawn_entity(
        world,
        [
            IdentityComponent(name="Skill Spark", kind="spell"),
            SpellComponent(name="Skill Spark", skill_name="destruction", min_skill_level=2),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), skill_spell.id)
    distant_spell = spawn_entity(
        world,
        [IdentityComponent(name="Far Spark", kind="spell"), SpellComponent(name="Far Spark")],
    )
    recipe = spawn_entity(
        world,
        [
            IdentityComponent(name="hard recipe", kind="recipe"),
            PotionRecipeComponent(
                name="hard recipe",
                potion_name="Hard Tonic",
                min_skill_level=2,
            ),
        ],
    )
    missing_ingredient = spawn_entity(
        world,
        [IdentityComponent(name="missing herb", kind="item"), PortableComponent()],
    )
    missing_ingredient_recipe = spawn_entity(
        world,
        [
            IdentityComponent(name="missing recipe", kind="recipe"),
            PotionRecipeComponent(
                name="missing recipe",
                potion_name="Missing Tonic",
                skill_name="",
            ),
        ],
    )
    missing_ingredient_recipe.add_relationship(DependsOnIngredient(), missing_ingredient.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), recipe.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), missing_ingredient_recipe.id)
    empty_artifact = spawn_entity(
        world,
        [
            IdentityComponent(name="spent mirror", kind="artifact"),
            ArtifactComponent(name="Spent Mirror", charges=0),
        ],
    )
    identified_artifact = spawn_entity(
        world,
        [
            IdentityComponent(name="known mirror", kind="artifact"),
            ArtifactComponent(name="Known Mirror", identified_by=(str(scenario.character),)),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), empty_artifact.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), identified_artifact.id)
    beast = spawn_entity(
        world,
        [IdentityComponent(name="wyrm", kind="character"), AncientBeastComponent(name="wyrm")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), beast.id)
    word = _word(scenario, min_souls=0)
    paper = spawn_entity(
        world,
        [IdentityComponent(name="tiny paper", kind="item"), WritableComponent(remaining_space=2)],
    )
    studied_slate = spawn_entity(
        world,
        [
            IdentityComponent(name="studied slate", kind="prop"),
            VoiceInscriptionComponent(word_id=str(word), studied_by=(str(scenario.character),)),
        ],
    )
    broken_slate = spawn_entity(
        world,
        [
            IdentityComponent(name="broken slate", kind="prop"),
            VoiceInscriptionComponent(word_id="not-an-id"),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), paper.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), studied_slate.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), broken_slate.id)

    cases = [
        (
            ChangeFactionRankHandler(),
            _handler_cmd(scenario, "change-faction-rank", faction_id=str(wrong_kind.id), rank="x"),
            "target is not a faction",
        ),
        (
            ChangeFactionRankHandler(),
            _handler_cmd(scenario, "change-faction-rank", faction_id=str(faction), rank="x"),
            "not a faction member",
        ),
        (
            BribeGuardHandler(),
            _handler_cmd(scenario, "bribe", guard_id=str(distant_npc.id)),
            "guard is not reachable",
        ),
        (
            BribeGuardHandler(),
            _handler_cmd(scenario, "bribe", guard_id=str(wrong_kind.id)),
            "target is not a guard",
        ),
        (ServeJailTimeHandler(), _handler_cmd(scenario, "serve-jail-time"), "not jailed"),
        (
            PickLockHandler(),
            _handler_cmd(scenario, "pick-lock", lock_id=str(wrong_kind.id)),
            "target is not locked",
        ),
        (
            PickLockHandler(),
            _handler_cmd(scenario, "pick-lock", lock_id=str(locked_chest.id)),
            "lock is already open",
        ),
        (
            PickLockHandler(),
            _handler_cmd(scenario, "pick-lock", lock_id=str(hard_lock.id)),
            "lockpicking skill too low",
        ),
        (
            LearnSpellHandler(),
            _handler_cmd(scenario, "learn-spell", spell_id=str(distant_spell.id)),
            "spell is not reachable",
        ),
        (
            LearnSpellHandler(),
            _handler_cmd(scenario, "learn-spell", spell_id=str(wrong_kind.id)),
            "target is not a spell",
        ),
        (
            LearnSpellHandler(),
            _handler_cmd(scenario, "learn-spell", spell_id=str(skill_spell.id)),
            "skill level too low for this spell",
        ),
        (
            CastDragonSpellHandler(),
            _handler_cmd(scenario, "cast-dragon-spell", spell_id=str(wrong_kind.id)),
            "target is not a spell",
        ),
        (
            CastDragonSpellHandler(),
            _handler_cmd(scenario, "cast-dragon-spell", spell_id=str(cooldown_spell.id)),
            "spell is on cooldown",
        ),
        (
            CastDragonSpellHandler(),
            _handler_cmd(scenario, "cast-dragon-spell", spell_id=str(expensive_spell.id)),
            "not enough magic",
        ),
        (
            BrewPotionHandler(),
            _handler_cmd(scenario, "brew-potion", recipe_id=str(wrong_kind.id)),
            "target is not a potion recipe",
        ),
        (
            BrewPotionHandler(),
            _handler_cmd(scenario, "brew-potion", recipe_id=str(recipe.id)),
            "skill level too low for this recipe",
        ),
        (
            BrewPotionHandler(),
            _handler_cmd(scenario, "brew-potion", recipe_id=str(missing_ingredient_recipe.id)),
            "required ingredient is not carried",
        ),
        (
            UseArtifactHandler(),
            _handler_cmd(scenario, "use", item_id=str(wrong_kind.id)),
            "target is not an artifact",
        ),
        (
            UseArtifactHandler(),
            _handler_cmd(scenario, "use", item_id=str(empty_artifact.id)),
            "artifact has no charges",
        ),
        (
            RecoverMagicHandler(),
            _handler_cmd(scenario, "recover-magic", amount=0),
            "recovery amount must be positive",
        ),
        (
            IdentifyArtifactHandler(),
            _handler_cmd(scenario, "identify", artifact_id=str(wrong_kind.id)),
            "target is not an artifact",
        ),
        (
            IdentifyArtifactHandler(),
            _handler_cmd(scenario, "identify", artifact_id=str(identified_artifact.id)),
            "artifact already identified",
        ),
        (
            AppeaseAncientBeastHandler(),
            _handler_cmd(scenario, "appease-ancient-beast", beast_id=str(wrong_kind.id)),
            "target is not an ancient beast",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(
                scenario,
                "inscribe-voice-phrase",
                target_id=str(paper.id),
                word_id=str(word),
                phrase="",
            ),
            "nothing to inscribe",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(
                scenario,
                "inscribe-voice-phrase",
                target_id=str(wrong_kind.id),
                word_id=str(word),
                phrase="shout",
            ),
            "target is not writable or carvable",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(
                scenario,
                "inscribe-voice-phrase",
                target_id=str(paper.id),
                word_id=str(word),
                phrase="shout",
            ),
            "not enough room to inscribe that",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(
                scenario,
                "inscribe-voice-phrase",
                target_id=str(paper.id),
                word_id=str(wrong_kind.id),
                phrase="ok",
            ),
            "target word is not a word of power",
        ),
        (
            StudyVoiceInscriptionHandler(),
            _handler_cmd(scenario, "study-voice-inscription", target_id=str(wrong_kind.id)),
            "target has no voice inscription",
        ),
        (
            StudyVoiceInscriptionHandler(),
            _handler_cmd(scenario, "study-voice-inscription", target_id=str(broken_slate.id)),
            "voice inscription has no valid word",
        ),
        (
            StudyVoiceInscriptionHandler(),
            _handler_cmd(scenario, "study-voice-inscription", target_id=str(studied_slate.id)),
            "voice inscription already studied",
        ),
        (
            PersuadeHandler(),
            _handler_cmd(scenario, "persuade", target_id=str(distant_npc.id)),
            "target is not reachable",
        ),
        (
            ReportCrimeHandler(),
            _handler_cmd(
                scenario,
                "report-crime",
                criminal_id=str(distant_npc.id),
                faction_id=str(faction),
            ),
            "criminal is not reachable",
        ),
        (
            ReportCrimeHandler(),
            _handler_cmd(
                scenario,
                "report-crime",
                criminal_id=str(beast.id),
                faction_id=str(wrong_kind.id),
            ),
            "target is not a faction",
        ),
        (
            ReportCrimeHandler(),
            _handler_cmd(
                scenario,
                "report-crime",
                criminal_id=str(beast.id),
                faction_id=str(faction),
                bounty=0,
            ),
            "bounty must be positive",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def _encounter_zone(scenario):
    zone = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="wolf road", kind="location"),
            PointOfInterestComponent(location_type="road", region="north meadow"),
            EncounterZoneComponent(zone_type="wolf ambush", danger_rating=2),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), zone.id
    )
    return zone.id


def _quest(scenario):
    quest = spawn_entity(
        scenario.actor.world,
        [
            QuestComponent(quest_id="lost-ring", title="Find the Lost Ring"),
            QuestStateComponent(),
        ],
    )
    objective = spawn_entity(
        scenario.actor.world,
        [QuestObjectiveComponent(description="Recover the ring from the watchtower")],
    )
    quest.add_relationship(QuestHasObjective(), objective.id)
    return quest.id, objective.id


def _quest_reward(scenario, quest_id="lost-ring"):
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="silver carrot", kind="item"),
            PortableComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )
    reward = spawn_entity(
        scenario.actor.world,
        [QuestRewardComponent(description="A silver carrot")],
    )
    quest_result = next(
        entity
        for entity in scenario.actor.world.query().with_all([QuestComponent]).execute_entities()
        if entity.get_component(QuestComponent).quest_id == quest_id
    )
    quest_result.add_relationship(QuestHasReward(), reward.id)
    reward.add_relationship(QuestRewardGrants(), item.id)
    return reward.id, item.id


def _faction(scenario):
    faction = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moss Wardens", kind="faction"),
            FactionComponent(name="Moss Wardens", ideology="protect the burrow"),
        ],
    )
    return faction.id


def _skill_book(scenario):
    book = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Manual of Quiet Feet", kind="book"),
            PortableComponent(),
            LoreBookComponent(
                title="Manual of Quiet Feet",
                lore="A spy's marginalia explains how to cross creaking floors.",
                skill_name="stealth",
                skill_xp=12.0,
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), book.id
    )
    return book.id


async def test_discover_location_marks_poi_and_records_discovery():
    scenario = build_scenario()
    _install(scenario.actor)
    poi = _poi(scenario)
    discovered: list[LocationDiscoveredEvent] = []
    scenario.actor.bus.subscribe(LocationDiscoveredEvent, discovered.append)

    await scenario.actor.submit(_cmd(scenario, "discover-location", location_id=str(poi)))
    await scenario.actor.tick(HOUR)

    entity = scenario.actor.world.get_entity(poi)
    assert entity.get_component(PointOfInterestComponent).discovered is True
    assert str(scenario.character) in entity.get_component(DiscoveryComponent).discovered_by
    assert discovered[0].location_type == "ruin"


async def test_mark_map_records_marker_for_character():
    scenario = build_scenario()
    _install(scenario.actor)
    poi = _poi(scenario)
    marked: list[MapMarkerAddedEvent] = []
    scenario.actor.bus.subscribe(MapMarkerAddedEvent, marked.append)

    await scenario.actor.submit(
        _cmd(scenario, "mark-map", location_id=str(poi), label="Old Watchtower")
    )
    await scenario.actor.tick(HOUR)

    marker = scenario.actor.world.get_entity(poi).get_component(MapMarkerComponent)
    assert marker.label == "Old Watchtower"
    assert marker.marker_type == "ruin"
    assert marker.marked_by == (str(scenario.character),)
    assert marked[0].location_id == str(poi)
    character = scenario.actor.world.get_entity(scenario.character)
    assert "Map marker: Old Watchtower (ruin)." in dragonsim_fragments(
        scenario.actor.world, character
    )


async def test_trigger_encounter_zone_updates_last_triggered_epoch():
    scenario = build_scenario()
    _install(scenario.actor)
    zone = _encounter_zone(scenario)
    triggered: list[EncounterTriggeredEvent] = []
    scenario.actor.bus.subscribe(EncounterTriggeredEvent, triggered.append)

    await scenario.actor.submit(_cmd(scenario, "trigger-encounter", zone_id=str(zone)))
    await scenario.actor.tick(HOUR)

    component = scenario.actor.world.get_entity(zone).get_component(EncounterZoneComponent)
    assert component.last_triggered_at_epoch == HOUR
    assert triggered[0].zone_type == "wolf ambush"
    assert triggered[0].danger_rating == 2


async def test_accept_and_complete_quest_objective_completes_quest_and_grants_reward():
    scenario = build_scenario()
    _install(scenario.actor)
    quest, objective = _quest(scenario)
    reward, item = _quest_reward(scenario)
    accepted: list[QuestAcceptedEvent] = []
    completed_objectives: list[QuestObjectiveCompletedEvent] = []
    completed_quests: list[QuestCompletedEvent] = []
    scenario.actor.bus.subscribe(QuestAcceptedEvent, accepted.append)
    scenario.actor.bus.subscribe(QuestObjectiveCompletedEvent, completed_objectives.append)
    scenario.actor.bus.subscribe(QuestCompletedEvent, completed_quests.append)

    await scenario.actor.submit(_cmd(scenario, "accept-quest", quest_id=str(quest)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "complete-objective", objective_id=str(objective)))
    await scenario.actor.tick(HOUR)

    quest_component = scenario.actor.world.get_entity(quest).get_component(QuestStateComponent)
    objective_component = scenario.actor.world.get_entity(objective).get_component(
        QuestObjectiveComponent
    )
    assert accepted[0].title == "Find the Lost Ring"
    assert objective_component.completed is True
    assert completed_objectives[0].objective_id == str(objective)
    assert quest_component.status == "completed"
    assert completed_quests[0].quest_key == "lost-ring"
    assert container_of(scenario.actor.world.get_entity(item)) == scenario.character
    reward_component = scenario.actor.world.get_entity(reward).get_component(QuestRewardComponent)
    assert reward_component.claimed is True
    assert reward_component.claimed_by == str(scenario.character)


async def test_complete_quest_grants_reward_item_without_source_container():
    scenario = build_scenario()
    _install(scenario.actor)
    quest, objective = _quest(scenario)
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="loose silver carrot", kind="item"),
            PortableComponent(),
        ],
    )
    reward = spawn_entity(
        scenario.actor.world,
        [QuestRewardComponent(description="A loose silver carrot")],
    )
    scenario.actor.world.get_entity(quest).add_relationship(QuestHasReward(), reward.id)
    reward.add_relationship(QuestRewardGrants(), item.id)
    completed_quests: list[QuestCompletedEvent] = []
    scenario.actor.bus.subscribe(QuestCompletedEvent, completed_quests.append)

    await scenario.actor.submit(_cmd(scenario, "accept-quest", quest_id=str(quest)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "complete-objective", objective_id=str(objective)))
    await scenario.actor.tick(HOUR)

    assert completed_quests[0].quest_key == "lost-ring"
    assert container_of(item) == scenario.character


async def test_complete_nonfinal_objective_by_description_keeps_quest_active():
    scenario = build_scenario()
    _install(scenario.actor)
    quest, objective = _quest(scenario)
    second_objective = spawn_entity(
        scenario.actor.world,
        [
            QuestObjectiveComponent(
                description="Report back to the warden",
            )
        ],
    )
    scenario.actor.world.get_entity(quest).add_relationship(
        QuestHasObjective(order=1), second_objective.id
    )
    completed_objectives: list[QuestObjectiveCompletedEvent] = []
    completed_quests: list[QuestCompletedEvent] = []
    scenario.actor.bus.subscribe(QuestObjectiveCompletedEvent, completed_objectives.append)
    scenario.actor.bus.subscribe(QuestCompletedEvent, completed_quests.append)

    await scenario.actor.submit(_cmd(scenario, "accept-quest", quest_id=str(quest)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "complete-objective",
            objective_id="Recover the ring from the watchtower",
        )
    )
    await scenario.actor.tick(HOUR)

    quest_component = scenario.actor.world.get_entity(quest).get_component(QuestStateComponent)
    objective_component = scenario.actor.world.get_entity(objective).get_component(
        QuestObjectiveComponent
    )
    assert objective_component.completed is True
    assert completed_objectives[0].description == "Recover the ring from the watchtower"
    assert quest_component.status == "active"
    assert completed_quests == []


async def test_read_lore_book_marks_book_and_grants_lifesim_skill_xp_once():
    scenario = build_scenario()
    _install(scenario.actor)
    book = _skill_book(scenario)
    read: list[LoreBookReadEvent] = []
    scenario.actor.bus.subscribe(LoreBookReadEvent, read.append)

    await scenario.actor.submit(_cmd(scenario, "read-lore-book", book_id=str(book)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "read-lore-book", book_id=str(book)))
    await scenario.actor.tick(HOUR)

    book_component = scenario.actor.world.get_entity(book).get_component(LoreBookComponent)
    skills = scenario.actor.world.get_entity(scenario.character).get_component(SkillSetComponent)
    assert book_component.read_by == (str(scenario.character),)
    assert skills.xp["stealth"] == 12.0
    assert [event.skill_xp_awarded for event in read] == [12.0, 0.0]


async def test_read_lore_book_without_skill_only_marks_read():
    scenario = build_scenario()
    _install(scenario.actor)
    book = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hold Almanac", kind="book"),
            PortableComponent(),
            LoreBookComponent(title="Hold Almanac", lore="Boundary stones and old roads."),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), book.id
    )
    character = scenario.actor.world.get_entity(scenario.character)
    assert "Unread lore book nearby: Hold Almanac." in dragonsim_fragments(
        scenario.actor.world, character
    )
    read: list[LoreBookReadEvent] = []
    scenario.actor.bus.subscribe(LoreBookReadEvent, read.append)

    await scenario.actor.submit(_cmd(scenario, "read-lore-book", book_id=str(book.id)))
    await scenario.actor.tick(HOUR)

    assert read and read[0].skill_xp_awarded == 0.0
    assert book.get_component(LoreBookComponent).read_by == (str(scenario.character),)
    assert not character.has_component(SkillSetComponent)


def test_dragonsim_handlers_reject_invalid_targets_and_states_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain stone", kind="prop")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    distant_poi = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far watchtower", kind="location"),
            PointOfInterestComponent(location_type="ruin", region="north meadow"),
        ],
    )
    distant_book = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far manual", kind="book"),
            LoreBookComponent(title="Far Manual"),
        ],
    )
    discovered_poi = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="known watchtower", kind="location"),
            PointOfInterestComponent(location_type="ruin", region="north meadow"),
            DiscoveryComponent(discovered_by=(str(scenario.character),)),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), discovered_poi.id)
    marked_poi = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="marked watchtower", kind="location"),
            PointOfInterestComponent(location_type="ruin", region="north meadow"),
            MapMarkerComponent(marked_by=(str(scenario.character),)),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), marked_poi.id)
    distant_zone = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far wolf road", kind="location"),
            EncounterZoneComponent(zone_type="wolf ambush"),
        ],
    )
    inactive_zone = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="quiet wolf road", kind="location"),
            EncounterZoneComponent(zone_type="wolf ambush", active=False),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), inactive_zone.id)
    offered_quest = spawn_entity(
        scenario.actor.world,
        [
            QuestComponent(quest_id="guard-duty", title="Guard Duty"),
            QuestStateComponent(),
        ],
    )
    active_quest = spawn_entity(
        scenario.actor.world,
        [
            QuestComponent(
                quest_id="active-duty",
                title="Active Duty",
            ),
            QuestStateComponent(status="active"),
        ],
    )
    completed_quest = spawn_entity(
        scenario.actor.world,
        [
            QuestComponent(
                quest_id="done-duty",
                title="Done Duty",
            ),
            QuestStateComponent(status="completed"),
        ],
    )
    objective = spawn_entity(
        scenario.actor.world,
        [QuestObjectiveComponent(description="Stand watch")],
    )
    completed_objective = spawn_entity(
        scenario.actor.world,
        [
            QuestObjectiveComponent(
                description="Already stood watch",
                completed=True,
            )
        ],
    )
    orphan_objective = spawn_entity(
        scenario.actor.world,
        [QuestObjectiveComponent(description="No quest")],
    )
    offered_quest.add_relationship(QuestHasObjective(), objective.id)
    offered_quest.add_relationship(QuestHasObjective(order=1), completed_objective.id)
    active_quest.add_relationship(QuestAcceptedBy(), scenario.character)
    faction = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moss Wardens", kind="faction"),
            FactionComponent(name="Moss Wardens", ideology="protect the burrow"),
        ],
    )

    cases = [
        (
            DiscoverLocationHandler(),
            _handler_cmd(
                scenario,
                "discover-location",
                character_id="not-an-id",
                location_id=str(distant_poi.id),
            ),
            "invalid character or location id",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(scenario, "discover-location", location_id="entity_999"),
            "location does not exist",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(
                scenario,
                "discover-location",
                location_id=str(distant_poi.id),
            ),
            "location is not reachable",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(scenario, "discover-location", location_id=str(wrong_kind.id)),
            "target is not discoverable",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(
                scenario,
                "discover-location",
                location_id=str(discovered_poi.id),
            ),
            "location already discovered",
        ),
        (
            MarkMapHandler(),
            _handler_cmd(
                scenario,
                "mark-map",
                character_id="not-an-id",
                location_id=str(distant_poi.id),
            ),
            "invalid character or location id",
        ),
        (
            MarkMapHandler(),
            _handler_cmd(scenario, "mark-map", location_id="entity_999"),
            "location does not exist",
        ),
        (
            MarkMapHandler(),
            _handler_cmd(scenario, "mark-map", location_id=str(distant_poi.id)),
            "location is not reachable",
        ),
        (
            MarkMapHandler(),
            _handler_cmd(scenario, "mark-map", location_id=str(wrong_kind.id)),
            "target is not a mappable location",
        ),
        (
            MarkMapHandler(),
            _handler_cmd(scenario, "mark-map", location_id=str(marked_poi.id)),
            "location is already marked",
        ),
        (
            TriggerEncounterHandler(),
            _handler_cmd(
                scenario,
                "trigger-encounter",
                character_id="not-an-id",
                zone_id=str(distant_zone.id),
            ),
            "invalid character or encounter zone id",
        ),
        (
            TriggerEncounterHandler(),
            _handler_cmd(scenario, "trigger-encounter", zone_id="entity_999"),
            "encounter zone does not exist",
        ),
        (
            TriggerEncounterHandler(),
            _handler_cmd(
                scenario,
                "trigger-encounter",
                zone_id=str(distant_zone.id),
            ),
            "encounter zone is not reachable",
        ),
        (
            TriggerEncounterHandler(),
            _handler_cmd(scenario, "trigger-encounter", zone_id=str(wrong_kind.id)),
            "target is not an encounter zone",
        ),
        (
            TriggerEncounterHandler(),
            _handler_cmd(scenario, "trigger-encounter", zone_id=str(inactive_zone.id)),
            "encounter zone is inactive",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", character_id="not-an-id", quest_id="x"),
            "invalid character or quest id",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", quest_id="missing"),
            "quest does not exist",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", quest_id=str(wrong_kind.id)),
            "target is not a quest",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", quest_id=str(completed_quest.id)),
            "quest is already complete",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", quest_id=str(active_quest.id)),
            "quest already accepted",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(
                scenario,
                "complete-objective",
                character_id="not-an-id",
                objective_id=str(objective.id),
            ),
            "invalid character or objective id",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(scenario, "complete-objective", objective_id="missing"),
            "objective does not exist",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(
                scenario,
                "complete-objective",
                objective_id=str(wrong_kind.id),
            ),
            "target is not a quest objective",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(
                scenario,
                "complete-objective",
                objective_id=str(completed_objective.id),
            ),
            "objective is already complete",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(
                scenario,
                "complete-objective",
                objective_id=str(orphan_objective.id),
            ),
            "quest does not exist",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(scenario, "complete-objective", objective_id=str(objective.id)),
            "quest is not accepted",
        ),
        (
            JoinFactionHandler(),
            _handler_cmd(
                scenario,
                "join-faction",
                character_id="not-an-id",
                faction_id=str(faction.id),
            ),
            "invalid character or faction id",
        ),
        (
            JoinFactionHandler(),
            _handler_cmd(scenario, "join-faction", faction_id="entity_999"),
            "faction does not exist",
        ),
        (
            JoinFactionHandler(),
            _handler_cmd(scenario, "join-faction", faction_id=str(wrong_kind.id)),
            "target is not a faction",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(
                scenario,
                "leave-faction",
                character_id="not-an-id",
                faction_id=str(faction.id),
            ),
            "invalid character or faction id",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(scenario, "leave-faction", faction_id="entity_999"),
            "faction does not exist",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(scenario, "leave-faction", faction_id=str(wrong_kind.id)),
            "target is not a faction",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(scenario, "leave-faction", faction_id=str(faction.id)),
            "not a faction member",
        ),
        (
            ReadLoreBookHandler(),
            _handler_cmd(
                scenario,
                "read-lore-book",
                character_id="not-an-id",
                book_id=str(distant_book.id),
            ),
            "invalid character or book id",
        ),
        (
            ReadLoreBookHandler(),
            _handler_cmd(scenario, "read-lore-book", book_id=str(distant_book.id)),
            "book is not reachable",
        ),
        (
            ReadLoreBookHandler(),
            _handler_cmd(scenario, "read-lore-book", book_id=str(wrong_kind.id)),
            "target is not a lore book",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOfFaction(rank="member", since_epoch=0), faction.id)
    result = JoinFactionHandler().execute(
        ctx,
        _handler_cmd(scenario, "join-faction", faction_id=str(faction.id)),
    )
    assert result.ok is False
    assert result.reason == "already a faction member"


async def test_complete_objective_rejects_unaccepted_quest():
    scenario = build_scenario()
    _install(scenario.actor)
    _quest_id, objective = _quest(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "complete-objective", objective_id=str(objective)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "quest is not accepted" for event in rejects)


async def test_join_and_leave_faction_updates_membership_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    joined: list[FactionJoinedEvent] = []
    left: list[FactionLeftEvent] = []
    scenario.actor.bus.subscribe(FactionJoinedEvent, joined.append)
    scenario.actor.bus.subscribe(FactionLeftEvent, left.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-faction", faction_id=str(faction), rank="scout")
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(MemberOfFaction, faction)
    assert joined[0].rank == "scout"

    await scenario.actor.submit(_cmd(scenario, "leave-faction", faction_id=str(faction)))
    await scenario.actor.tick(HOUR)

    assert not character.has_relationship(MemberOfFaction, faction)
    assert left[0].faction_name == "Moss Wardens"


def test_dragonsim_fragments_show_quests_factions_and_nearby_locations():
    scenario = build_scenario()
    poi = _poi(scenario)
    faction = _faction(scenario)
    nameless_group = spawn_entity(scenario.actor.world, [])
    quest, _objective = _quest(scenario)
    book = _skill_book(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOfFaction(rank="scout", since_epoch=0), faction)
    character.add_relationship(MemberOfFaction(rank="ally", since_epoch=0), nameless_group.id)
    quest_entity = scenario.actor.world.get_entity(quest)
    replace_component(quest_entity, QuestStateComponent(status="active"))
    quest_entity.add_relationship(QuestAcceptedBy(), scenario.character)

    fragments = dragonsim_fragments(scenario.actor.world, character)

    assert scenario.actor.world.get_entity(poi).has_component(PointOfInterestComponent)
    assert any("Moss Wardens" in line for line in fragments)
    assert any(f"ally of {nameless_group.id}" in line for line in fragments)
    assert any("Active quest: Find the Lost Ring" in line for line in fragments)
    assert any("old watchtower" in line for line in fragments)
    assert any("Manual of Quiet Feet" in line and "stealth" in line for line in fragments)
    assert scenario.actor.world.get_entity(book).has_component(LoreBookComponent)


def test_dragonsim_component_prompt_fragments_use_target_context():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    quest = spawn_entity(
        world,
        [
            QuestComponent(
                quest_id="lost-ring",
                title="Find the Lost Ring",
            ),
            QuestStateComponent(status="active"),
        ],
    )
    quest.add_relationship(QuestAcceptedBy(), character.id)
    spell = spawn_entity(world, [SpellComponent(name="Oakflesh")])
    artifact = spawn_entity(
        world,
        [ArtifactComponent(name="Moon Amulet", charges=2, identified_by=(str(character.id),))],
    )
    character.add_relationship(KnowsSpell(), spell.id)
    self_ctx = ComponentPromptContext.for_entity(world, character)
    observer = spawn_entity(world, [CharacterComponent()])
    target_ctx = ComponentPromptContext.for_entity(
        world, quest, perspective=self_ctx.perspective, target=character
    )
    learned_ctx = ComponentPromptContext.for_entity(world, spell)
    reachable_spell_ctx = ComponentPromptContext.for_entity(
        world, spell, perspective=self_ctx.perspective, target=character
    )
    observer_spell_ctx = ComponentPromptContext.for_entity(
        world,
        spell,
        perspective=PromptPerspective(viewer=observer),
        target=character,
    )
    artifact_ctx = ComponentPromptContext.for_entity(
        world, artifact, perspective=self_ctx.perspective, target=character
    )

    assert quest.get_component(QuestComponent).prompt_fragments(target_ctx) == (
        "Active quest: Find the Lost Ring.",
    )
    assert spell.get_component(SpellComponent).prompt_fragments(learned_ctx) == (
        "Spell learned: Oakflesh.",
    )
    assert spell.get_component(SpellComponent).prompt_fragments(reachable_spell_ctx) == (
        "Spell learned: Oakflesh.",
    )
    assert spell.get_component(SpellComponent).prompt_fragments(observer_spell_ctx) == ()
    assert PerkComponent(name="Power Attack", skill_name="blade").prompt_fragments(
        reachable_spell_ctx
    ) == ("Perk unlocked: Power Attack.",)
    assert (
        PerkComponent(name="Power Attack", skill_name="blade").prompt_fragments(observer_spell_ctx)
        == ()
    )
    assert WordOfPowerComponent(name="Fus").prompt_fragments(reachable_spell_ctx) == (
        "Word of power known: Fus.",
    )
    assert WordOfPowerComponent(name="Fus").prompt_fragments(observer_spell_ctx) == ()
    assert artifact.get_component(ArtifactComponent).prompt_fragments(artifact_ctx) == (
        "Artifact nearby: Moon Amulet (2 charges, identified).",
    )


def _set_skill_level(scenario, skill_name, level):
    """Set a lifesim skill level directly (lifesim owns skill-by-use progression)."""
    character = scenario.actor.world.get_entity(scenario.character)
    state = (
        character.get_component(SkillSetComponent)
        if character.has_component(SkillSetComponent)
        else SkillSetComponent()
    )
    levels = dict(state.levels)
    levels[skill_name] = level
    if character.has_component(SkillSetComponent):
        character.remove_component(SkillSetComponent)
    character.add_component(SkillSetComponent(levels=levels, xp=dict(state.xp)))


async def test_unlock_perk_gates_on_lifesim_skill_level():
    scenario = build_scenario()
    _install(scenario.actor)
    perk = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Power Attack", kind="perk"),
            PerkComponent(name="Power Attack", skill_name="blade", min_level=2),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    unlocked: list[PerkUnlockedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    scenario.actor.bus.subscribe(PerkUnlockedEvent, unlocked.append)

    # Skill not yet high enough.
    _set_skill_level(scenario, "blade", 1)
    await scenario.actor.submit(_cmd(scenario, "unlock-perk", perk_id=str(perk.id)))
    await scenario.actor.tick(HOUR)
    assert any("skill level too low" in event.reason for event in rejects)
    assert unlocked == []

    # Reach the gating level and unlock.
    _set_skill_level(scenario, "blade", 2)
    await scenario.actor.submit(_cmd(scenario, "unlock-perk", perk_id=str(perk.id)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(HasPerk, perk.id)
    assert unlocked[0].perk_name == "Power Attack"
    fragments = dragonsim_fragments(scenario.actor.world, character)
    assert any("Perk unlocked: Power Attack" in line for line in fragments)


def test_unlock_perk_rejects_invalid_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="not a perk", kind="prop")],
    )
    perk = spawn_entity(
        scenario.actor.world,
        [PerkComponent(name="Power Attack", skill_name="blade", min_level=2)],
    )

    unlock = UnlockPerkHandler()
    rejections = {
        unlock.execute(
            ctx, _handler_cmd(scenario, "unlock-perk", character_id="not-an-id", perk_id="x")
        ).reason,
        unlock.execute(ctx, _handler_cmd(scenario, "unlock-perk", perk_id="entity_999")).reason,
        unlock.execute(
            ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(wrong_kind.id))
        ).reason,
        # No SkillSetComponent at all -> treated as level 0.
        unlock.execute(ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(perk.id))).reason,
    }
    assert "invalid character or perk id" in rejections
    assert "perk does not exist" in rejections
    assert "target is not a perk" in rejections
    assert "skill level too low for this perk" in rejections

    # Once the gating skill is high enough, unlocking succeeds; a second unlock is rejected.
    _set_skill_level(scenario, "blade", 2)
    assert unlock.execute(ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(perk.id))).ok
    assert (
        unlock.execute(ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(perk.id))).reason
        == "perk already unlocked"
    )


def _dead_beast(scenario, name="Ancient Wyrm"):
    beast = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="character"),
            AncientBeastComponent(name=name),
            DeadComponent(died_at_epoch=0, cause="slain"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), beast.id
    )
    return beast.id


def _word(scenario, *, name="Unrelenting Force", min_souls=1, skill_name="", min_skill_level=0):
    return spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="word"),
            WordOfPowerComponent(
                name=name,
                min_souls=min_souls,
                skill_name=skill_name,
                min_skill_level=min_skill_level,
            ),
        ],
    ).id


async def test_absorb_great_soul_then_learn_and_speak_word():
    scenario = build_scenario()
    _install(scenario.actor)
    beast = _dead_beast(scenario)
    word = _word(scenario, skill_name="voice", min_skill_level=2)
    _set_skill_level(scenario, "voice", 2)
    absorbed: list[GreatSoulAbsorbedEvent] = []
    learned: list[WordOfPowerLearnedEvent] = []
    spoken: list[WordOfPowerSpokenEvent] = []
    scenario.actor.bus.subscribe(GreatSoulAbsorbedEvent, absorbed.append)
    scenario.actor.bus.subscribe(WordOfPowerLearnedEvent, learned.append)
    scenario.actor.bus.subscribe(WordOfPowerSpokenEvent, spoken.append)

    await scenario.actor.submit(_cmd(scenario, "absorb-great-soul", beast_id=str(beast)))
    await scenario.actor.tick(HOUR)
    assert absorbed[0].souls == 1
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(GreatSoulComponent).souls == 1
    assert scenario.actor.world.get_entity(beast).get_component(AncientBeastComponent).soul_absorbed

    await scenario.actor.submit(_cmd(scenario, "learn-word-of-power", word_id=str(word)))
    await scenario.actor.tick(HOUR)
    assert character.has_relationship(KnowsWord, word)
    assert learned[0].word_name == "Unrelenting Force"

    await scenario.actor.submit(_cmd(scenario, "speak-word-of-power", word_id=str(word)))
    await scenario.actor.tick(HOUR)
    assert spoken[0].word_name == "Unrelenting Force"

    fragments = dragonsim_fragments(scenario.actor.world, character)
    assert any("Great souls absorbed: 1" in line for line in fragments)
    assert any("Word of power known: Unrelenting Force" in line for line in fragments)


def test_soul_and_word_handlers_reject_invalid_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    living_beast = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Live Wyrm", kind="character"),
            AncientBeastComponent(name="Live Wyrm"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), living_beast.id
    )
    not_a_beast = spawn_entity(scenario.actor.world, [IdentityComponent(name="stump", kind="prop")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), not_a_beast.id
    )
    word = _word(scenario, min_souls=2, skill_name="voice", min_skill_level=2)

    absorb = AbsorbGreatSoulHandler()
    learn = LearnWordOfPowerHandler()
    speak = SpeakWordOfPowerHandler()

    assert (
        absorb.execute(
            ctx, _handler_cmd(scenario, "absorb-great-soul", character_id="x", beast_id="y")
        ).reason
        == "invalid character or beast id"
    )
    assert (
        absorb.execute(
            ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id="entity_999")
        ).reason
        == "beast does not exist"
    )
    assert (
        absorb.execute(
            ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(not_a_beast.id))
        ).reason
        == "target is not an ancient beast"
    )
    assert (
        absorb.execute(
            ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(living_beast.id))
        ).reason
        == "the beast still lives"
    )
    unreachable = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Distant Wyrm", kind="character"),
            AncientBeastComponent(name="Distant Wyrm"),
            DeadComponent(died_at_epoch=0, cause="slain"),
        ],
    )
    assert (
        absorb.execute(
            ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(unreachable.id))
        ).reason
        == "beast is not reachable"
    )

    # Word handler validation paths.
    assert (
        learn.execute(
            ctx, _handler_cmd(scenario, "learn-word-of-power", character_id="x", word_id="y")
        ).reason
        == "invalid character or word id"
    )
    assert (
        learn.execute(
            ctx, _handler_cmd(scenario, "learn-word-of-power", word_id="entity_999")
        ).reason
        == "word does not exist"
    )
    assert (
        learn.execute(
            ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(not_a_beast.id))
        ).reason
        == "target is not a word of power"
    )
    assert (
        speak.execute(
            ctx, _handler_cmd(scenario, "speak-word-of-power", character_id="x", word_id="y")
        ).reason
        == "invalid character or word id"
    )
    assert (
        speak.execute(
            ctx, _handler_cmd(scenario, "speak-word-of-power", word_id="entity_999")
        ).reason
        == "word does not exist"
    )

    # Learning is gated on souls, then on skill level.
    assert (
        speak.execute(ctx, _handler_cmd(scenario, "speak-word-of-power", word_id=str(word))).reason
        == "you have not learned that word"
    )
    assert (
        learn.execute(ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))).reason
        == "not enough great souls to learn this word"
    )

    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(GreatSoulComponent(souls=2))
    assert (
        learn.execute(ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))).reason
        == "skill level too low for this word"
    )

    _set_skill_level(scenario, "voice", 2)
    assert learn.execute(ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))).ok
    assert (
        learn.execute(ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))).reason
        == "word already learned"
    )

    # Re-absorbing a claimed soul is rejected.
    dead = _dead_beast(scenario, name="Claimed Wyrm")
    assert absorb.execute(ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(dead))).ok
    assert (
        absorb.execute(ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(dead))).reason
        == "its great soul is already claimed"
    )


async def test_voice_phrase_can_be_inscribed_on_writable_or_carvable_target_and_studied():
    scenario = build_scenario()
    _install(scenario.actor)
    word = _word(scenario, name="Storm Call", min_souls=0)
    slate = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="scratched slate", kind="prop"),
            CarvableComponent(remaining_space=40),
        ],
    )
    paper = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="blank paper", kind="item"),
            WritableComponent(remaining_space=40),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), slate.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), paper.id)
    inscribed: list[VoicePhraseInscribedEvent] = []
    studied: list[VoiceInscriptionStudiedEvent] = []
    scenario.actor.bus.subscribe(VoicePhraseInscribedEvent, inscribed.append)
    scenario.actor.bus.subscribe(VoiceInscriptionStudiedEvent, studied.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "inscribe-voice-phrase",
            target_id=str(slate.id),
            word_id=str(word),
            phrase="storm listens",
        )
    )
    await scenario.actor.tick(HOUR)

    assert slate.get_component(VoiceInscriptionComponent).word_id == str(word)
    assert slate.get_component(ReadableComponent).text == "storm listens"
    assert slate.get_component(CarvableComponent).remaining_space == 27
    assert inscribed[0].target_id == str(slate.id)

    await scenario.actor.submit(_cmd(scenario, "study-voice-inscription", target_id=str(slate.id)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(KnowsWord, word)
    assert studied[0].word_id == str(word)
    assert any(
        "Word of power known: Storm Call" in line
        for line in dragonsim_fragments(scenario.actor.world, character)
    )

    await scenario.actor.submit(
        _cmd(
            scenario,
            "inscribe-voice-phrase",
            target_id=str(paper.id),
            word_id=str(word),
            phrase="rain remembers",
        )
    )
    await scenario.actor.tick(HOUR)

    assert paper.get_component(ReadableComponent).text == "rain remembers"
    assert paper.get_component(WritableComponent).remaining_space == 26


async def test_change_rank_bribe_guard_serve_jail_and_pick_lock():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOfFaction(rank="scout", since_epoch=3), faction)
    character.add_component(WantedComponent(amounts={str(faction): 15}))
    guard = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moss Guard", kind="character"),
            CharacterComponent(species="bunny"),
            GuardComponent(faction_id=str(faction), bribe_amount=10),
        ],
    )
    lock = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="old chest", kind="container"),
            LockDifficultyComponent(difficulty=2),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), guard.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), lock.id)
    _set_skill_level(scenario, "lockpicking", 2)
    ranked: list[FactionRankChangedEvent] = []
    bribed: list[GuardBribedEvent] = []
    jailed: list[JailSentenceServedEvent] = []
    picked: list[LockPickedEvent] = []
    scenario.actor.bus.subscribe(FactionRankChangedEvent, ranked.append)
    scenario.actor.bus.subscribe(GuardBribedEvent, bribed.append)
    scenario.actor.bus.subscribe(JailSentenceServedEvent, jailed.append)
    scenario.actor.bus.subscribe(LockPickedEvent, picked.append)

    await scenario.actor.submit(
        _cmd(scenario, "change-faction-rank", faction_id=str(faction), rank="warden")
    )
    await scenario.actor.tick(HOUR)
    assert ranked[0].old_rank == "scout"
    assert ranked[0].new_rank == "warden"

    await scenario.actor.submit(_cmd(scenario, "bribe", guard_id=str(guard.id)))
    await scenario.actor.tick(HOUR)
    assert bribed[0].amount == 10
    assert character.get_component(WantedComponent).amounts[str(faction)] == 5

    character.remove_component(WantedComponent)
    character.add_component(WantedComponent(amounts={str(faction): 5}))
    character.add_component(JailComponent(faction_id=str(faction), release_epoch=0))
    await scenario.actor.submit(_cmd(scenario, "serve-jail-time"))
    await scenario.actor.tick(HOUR)
    assert not character.has_component(JailComponent)
    assert character.get_component(WantedComponent).amounts == {}
    assert jailed[0].faction_id == str(faction)

    await scenario.actor.submit(_cmd(scenario, "pick-lock", lock_id=str(lock.id)))
    await scenario.actor.tick(HOUR)
    assert lock.get_component(LockDifficultyComponent).locked is False
    assert picked[0].difficulty == 2
    assert character.get_component(SkillSetComponent).xp["lockpicking"] == 2.0


async def test_learn_cast_brew_and_use_fixed_adventure_magic():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(MagicComponent(current=5, maximum=5))
    _set_skill_level(scenario, "destruction", 1)
    _set_skill_level(scenario, "alchemy", 1)
    spell = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Spark", kind="spell"),
            SpellComponent(
                name="Spark",
                school="destruction",
                magic_cost=3,
                skill_name="destruction",
                min_skill_level=1,
            ),
        ],
    )
    herb = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="blue herb", kind="item"), PortableComponent()],
    )
    recipe = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="blue tonic recipe", kind="recipe"),
            PotionRecipeComponent(
                name="blue tonic recipe",
                potion_name="Blue Tonic",
                skill_name="alchemy",
                min_skill_level=1,
                effect="restore",
            ),
        ],
    )
    recipe.add_relationship(DependsOnIngredient(), herb.id)
    artifact = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="star mirror", kind="artifact"),
            ArtifactComponent(name="Star Mirror", effect="flare", charges=2),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), spell.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), recipe.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), artifact.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), herb.id)
    learned: list[SpellLearnedEvent] = []
    cast: list[DragonSpellCastEvent] = []
    brewed: list[PotionBrewedEvent] = []
    used: list[ArtifactUsedEvent] = []
    scenario.actor.bus.subscribe(SpellLearnedEvent, learned.append)
    scenario.actor.bus.subscribe(DragonSpellCastEvent, cast.append)
    scenario.actor.bus.subscribe(PotionBrewedEvent, brewed.append)
    scenario.actor.bus.subscribe(ArtifactUsedEvent, used.append)

    await scenario.actor.submit(_cmd(scenario, "learn-spell", spell_id=str(spell.id)))
    await scenario.actor.tick(HOUR)
    assert character.has_relationship(KnowsSpell, spell.id)
    assert learned[0].spell_name == "Spark"

    await scenario.actor.submit(_cmd(scenario, "cast-dragon-spell", spell_id=str(spell.id)))
    await scenario.actor.tick(HOUR)
    assert character.get_component(MagicComponent).current == 2
    assert cast[0].school == "destruction"
    assert character.get_component(SkillSetComponent).xp["destruction"] == 3.0

    await scenario.actor.submit(_cmd(scenario, "brew-potion", recipe_id=str(recipe.id)))
    await scenario.actor.tick(HOUR)
    potion = scenario.actor.world.get_entity(parse_entity_id(brewed[0].potion_id))
    assert potion.get_component(PotionComponent).name == "Blue Tonic"
    assert container_of(potion) == scenario.character
    assert container_of(herb) is None

    await scenario.actor.submit(_cmd(scenario, "use", item_id=str(artifact.id)))
    await scenario.actor.tick(HOUR)
    assert artifact.get_component(ArtifactComponent).charges == 1
    assert used[0].artifact_name == "Star Mirror"


def _victim_with_item(scenario, *, faction_id=None, room=None, name="Mara"):
    world = scenario.actor.world
    room = room if room is not None else scenario.room_a
    victim = spawn_entity(
        world,
        [IdentityComponent(name=name, kind="character"), CharacterComponent(species="bunny")],
    )
    world.get_entity(room).add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), victim.id)
    if faction_id is not None:
        victim.add_relationship(MemberOfFaction(rank="member"), faction_id)
    item = spawn_entity(
        world,
        [IdentityComponent(name="ruby ring", kind="item"), PortableComponent(can_pick_up=True)],
    )
    victim.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return victim.id, item.id


async def test_sneak_toggles_stealth_state():
    scenario = build_scenario()
    _install(scenario.actor)
    changes: list[StealthChangedEvent] = []
    scenario.actor.bus.subscribe(StealthChangedEvent, changes.append)

    await scenario.actor.submit(_cmd(scenario, "sneak"))
    await scenario.actor.tick(HOUR)
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(SneakingComponent).sneaking is True

    await scenario.actor.submit(_cmd(scenario, "sneak"))
    await scenario.actor.tick(HOUR)
    assert character.get_component(SneakingComponent).sneaking is False
    assert [event.sneaking for event in changes] == [True, False]


async def test_witnessed_theft_takes_item_and_raises_faction_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    victim, item = _victim_with_item(scenario, faction_id=faction)
    thefts: list[TheftCommittedEvent] = []
    crimes: list[CrimeWitnessedEvent] = []
    scenario.actor.bus.subscribe(TheftCommittedEvent, thefts.append)
    scenario.actor.bus.subscribe(CrimeWitnessedEvent, crimes.append)

    await scenario.actor.submit(_cmd(scenario, "steal", target_id=str(victim), item_id=str(item)))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert container_of(world.get_entity(item)) == scenario.character
    assert thefts and thefts[0].victim_id == str(victim)
    assert crimes and crimes[0].faction_id == str(faction)
    bounty = world.get_entity(scenario.character).get_component(WantedComponent)
    assert bounty.amounts[str(faction)] == 10


async def test_repeat_witnessed_theft_updates_existing_bounty_and_ignores_invalid_witnesses():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    victim, first_item = _victim_with_item(scenario, faction_id=faction)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    room.add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        spawn_entity(world, [IdentityComponent(name="statue", kind="prop")]).id,
    )
    sleeping_witness = spawn_entity(
        world,
        [
            IdentityComponent(name="sleeping scout", kind="character"),
            CharacterComponent(species="bunny"),
            SleepingComponent(started_at_epoch=0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), sleeping_witness.id)
    second_item = spawn_entity(
        world,
        [IdentityComponent(name="emerald ring", kind="item"), PortableComponent(can_pick_up=True)],
    )
    world.get_entity(victim).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), second_item.id
    )
    crimes: list[CrimeWitnessedEvent] = []
    scenario.actor.bus.subscribe(CrimeWitnessedEvent, crimes.append)

    await scenario.actor.submit(
        _cmd(scenario, "steal", target_id=str(victim), item_id=str(first_item))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "steal", target_id=str(victim), item_id=str(second_item.id))
    )
    await scenario.actor.tick(HOUR)

    bounty = world.get_entity(scenario.character).get_component(WantedComponent)
    assert bounty.amounts[str(faction)] == 20
    assert len(crimes) == 2
    assert str(sleeping_witness.id) not in crimes[-1].witness_ids


async def test_sneaking_thief_is_not_witnessed():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    victim, item = _victim_with_item(scenario, faction_id=faction)
    crimes: list[CrimeWitnessedEvent] = []
    scenario.actor.bus.subscribe(CrimeWitnessedEvent, crimes.append)

    await scenario.actor.submit(_cmd(scenario, "sneak"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "steal", target_id=str(victim), item_id=str(item)))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert container_of(world.get_entity(item)) == scenario.character
    assert not crimes
    assert not world.get_entity(scenario.character).has_component(WantedComponent)


async def test_pay_bounty_clears_a_faction_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    scenario.actor.world.get_entity(scenario.character).add_component(
        WantedComponent(amounts={str(faction): 30})
    )
    paid: list[BountyPaidEvent] = []
    scenario.actor.bus.subscribe(BountyPaidEvent, paid.append)

    await scenario.actor.submit(_cmd(scenario, "pay-bounty", faction_id=str(faction)))
    await scenario.actor.tick(HOUR)

    bounty = scenario.actor.world.get_entity(scenario.character).get_component(WantedComponent)
    assert str(faction) not in bounty.amounts
    assert paid and paid[0].amount == 30


def test_crime_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    faction = _faction(scenario)
    victim, item = _victim_with_item(scenario, faction_id=faction)
    stuck = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="anvil", kind="item"), PortableComponent(can_pick_up=False)],
    )
    scenario.actor.world.get_entity(victim).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), stuck.id
    )

    cases = [
        (StealHandler(), _handler_cmd(scenario, "steal", character_id="x"), "invalid thief"),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id="ghost_1", item_id=str(item)),
            "does not exist",
        ),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id=str(victim), item_id=str(stuck.id)),
            "cannot be taken",
        ),
        (
            PayBountyHandler(),
            _handler_cmd(scenario, "pay-bounty", faction_id="x"),
            "invalid character",
        ),
        (
            PayBountyHandler(),
            _handler_cmd(scenario, "pay-bounty", faction_id=str(faction)),
            "no bounties",
        ),
    ]
    for handler, command, expected in cases:
        result = handler.execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_dragonsim_fragments_show_sneaking_and_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(SneakingComponent(sneaking=True))
    character.add_component(WantedComponent(amounts={str(faction): 25}))

    lines = dragonsim_fragments(scenario.actor.world, character)
    assert any("sneaking" in line for line in lines)
    assert any("Bounty of 25" in line and "Moss Wardens" in line for line in lines)


async def test_theft_without_faction_witnesses_raises_no_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    victim, item = _victim_with_item(scenario)  # victim belongs to no faction
    crimes: list[CrimeWitnessedEvent] = []
    scenario.actor.bus.subscribe(CrimeWitnessedEvent, crimes.append)

    await scenario.actor.submit(_cmd(scenario, "steal", target_id=str(victim), item_id=str(item)))
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert container_of(world.get_entity(item)) == scenario.character
    assert not crimes
    assert not world.get_entity(scenario.character).has_component(WantedComponent)


def test_steal_and_sneak_reject_more_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    faction = _faction(scenario)
    far_victim, far_item = _victim_with_item(scenario, room=scenario.room_b, name="Bryn")
    near_victim, _near_item = _victim_with_item(scenario, faction_id=faction)
    loose = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="loose coin", kind="item"), PortableComponent(can_pick_up=True)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), loose.id
    )
    scenario.actor.world.get_entity(scenario.character).add_component(
        WantedComponent(amounts={str(faction): 10})
    )

    cases = [
        (SneakHandler(), _handler_cmd(scenario, "sneak", character_id="x"), "invalid character"),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id=str(far_victim), item_id=str(far_item)),
            "not present",
        ),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id=str(near_victim), item_id=str(loose.id)),
            "not carried",
        ),
        (
            PayBountyHandler(),
            _handler_cmd(scenario, "pay-bounty", faction_id="other_77"),
            "no bounty with that faction",
        ),
    ]
    for handler, command, expected in cases:
        result = handler.execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_fragments_show_bounty_for_unknown_faction_key():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(WantedComponent(amounts={"lost_77": 5}))

    lines = dragonsim_fragments(scenario.actor.world, character)
    assert any("Bounty of 5 with lost_77" in line for line in lines)


def test_payload_entity_id_returns_none_when_no_keys_present():
    # _payload_entity_id falls through to None when none of the keys are in the payload.
    # BribeGuardHandler.can_handle is the public path that calls it with no guard id.
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    assert BribeGuardHandler().can_handle(ctx, _handler_cmd(scenario, "bribe")) is False


def test_spell_component_first_person_fragment_hidden_without_private_state():
    scenario = build_scenario()
    world = scenario.actor.world
    spell = spawn_entity(world, [SpellComponent(name="Oakflesh")])
    observer = spawn_entity(world, [CharacterComponent()])
    # target=None path: not the learner's own private view -> empty.
    ctx = ComponentPromptContext.for_entity(
        world, spell, perspective=PromptPerspective(viewer=observer)
    )
    assert spell.get_component(SpellComponent).prompt_fragments(ctx) == ()


def test_quest_track_decline_branch_rejections_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    unaccepted = spawn_entity(
        world,
        [QuestComponent(quest_id="unaccepted", title="Unaccepted"), QuestStateComponent()],
    )
    completed = spawn_entity(
        world,
        [
            QuestComponent(quest_id="done", title="Done"),
            QuestStateComponent(status="completed"),
        ],
    )
    accepted = spawn_entity(
        world,
        [
            QuestComponent(
                quest_id="taken",
                title="Taken",
            ),
            QuestStateComponent(status="active"),
        ],
    )
    accepted.add_relationship(QuestAcceptedBy(), scenario.character)
    assert unaccepted and completed and accepted
    cases = [
        (
            TrackQuestHandler(),
            _handler_cmd(scenario, "track-quest", quest_id="unaccepted"),
            "quest is not accepted",
        ),
        (
            ChooseQuestBranchHandler(),
            _handler_cmd(scenario, "choose-quest-branch", quest_id="unaccepted", branch="left"),
            "quest is not accepted",
        ),
        (
            DeclineQuestHandler(),
            _handler_cmd(scenario, "decline-quest", quest_id="done"),
            "quest is already complete",
        ),
        (
            DeclineQuestHandler(),
            _handler_cmd(scenario, "decline-quest", quest_id="taken"),
            "accepted quest cannot be declined",
        ),
    ]
    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_adventure_handlers_reject_missing_and_unreachable_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    missing = "entity_999999"

    # Out-of-room (unreachable) entities of each kind.
    distant_guard = spawn_entity(
        world,
        [
            IdentityComponent(name="far guard", kind="character"),
            CharacterComponent(),
            GuardComponent(faction_id="f1", bribe_amount=5),
        ],
    )
    distant_lock = spawn_entity(
        world,
        [IdentityComponent(name="far chest", kind="container"), LockDifficultyComponent()],
    )
    distant_spell = spawn_entity(
        world, [IdentityComponent(name="far spell", kind="spell"), SpellComponent(name="Far")]
    )
    distant_recipe = spawn_entity(
        world,
        [
            IdentityComponent(name="far recipe", kind="recipe"),
            PotionRecipeComponent(name="far recipe", potion_name="Far Tonic"),
        ],
    )
    distant_artifact = spawn_entity(
        world,
        [
            IdentityComponent(name="far mirror", kind="artifact"),
            ArtifactComponent(name="Far Mirror", charges=1),
        ],
    )
    distant_beast = spawn_entity(
        world,
        [
            IdentityComponent(name="far wyrm", kind="character"),
            AncientBeastComponent(name="far wyrm"),
        ],
    )
    distant_slate = spawn_entity(
        world,
        [
            IdentityComponent(name="far slate", kind="prop"),
            VoiceInscriptionComponent(word_id="x"),
        ],
    )
    word = _word(scenario, min_souls=0)

    cases = [
        # invalid character/id, missing-entity, and unreachable paths per handler.
        (
            ChangeFactionRankHandler(),
            _handler_cmd(scenario, "change-faction-rank", character_id="x", faction_id="y"),
            "invalid character, faction, or rank",
        ),
        (
            ChangeFactionRankHandler(),
            _handler_cmd(scenario, "change-faction-rank", faction_id=missing, rank="warden"),
            "faction does not exist",
        ),
        (
            BribeGuardHandler(),
            _handler_cmd(scenario, "bribe", guard_id="x"),
            "invalid character or guard id",
        ),
        (
            BribeGuardHandler(),
            _handler_cmd(scenario, "bribe", guard_id=missing),
            "guard does not exist",
        ),
        (
            ServeJailTimeHandler(),
            _handler_cmd(scenario, "serve-jail-time", character_id="x"),
            "invalid character id",
        ),
        (
            PickLockHandler(),
            _handler_cmd(scenario, "pick-lock", lock_id="x"),
            "invalid character or lock id",
        ),
        (
            PickLockHandler(),
            _handler_cmd(scenario, "pick-lock", lock_id=missing),
            "lock does not exist",
        ),
        (
            PickLockHandler(),
            _handler_cmd(scenario, "pick-lock", lock_id=str(distant_lock.id)),
            "lock is not reachable",
        ),
        (
            LearnSpellHandler(),
            _handler_cmd(scenario, "learn-spell", spell_id="x"),
            "invalid character or spell id",
        ),
        (
            LearnSpellHandler(),
            _handler_cmd(scenario, "learn-spell", spell_id=missing),
            "spell does not exist",
        ),
        (
            CastDragonSpellHandler(),
            _handler_cmd(scenario, "cast-dragon-spell", spell_id="x"),
            "invalid character or spell id",
        ),
        (
            CastDragonSpellHandler(),
            _handler_cmd(scenario, "cast-dragon-spell", spell_id=missing),
            "spell does not exist",
        ),
        (
            CastDragonSpellHandler(),
            _handler_cmd(scenario, "cast-dragon-spell", spell_id=str(distant_spell.id)),
            "spell is not learned",
        ),
        (
            BrewPotionHandler(),
            _handler_cmd(scenario, "brew-potion", recipe_id="x"),
            "invalid character or recipe id",
        ),
        (
            BrewPotionHandler(),
            _handler_cmd(scenario, "brew-potion", recipe_id=missing),
            "recipe does not exist",
        ),
        (
            BrewPotionHandler(),
            _handler_cmd(scenario, "brew-potion", recipe_id=str(distant_recipe.id)),
            "recipe is not reachable",
        ),
        (
            UseArtifactHandler(),
            _handler_cmd(scenario, "use", artifact_id="x"),
            "invalid character or artifact id",
        ),
        (
            UseArtifactHandler(),
            _handler_cmd(scenario, "use", artifact_id=missing),
            "artifact does not exist",
        ),
        (
            UseArtifactHandler(),
            _handler_cmd(scenario, "use", artifact_id=str(distant_artifact.id)),
            "artifact is not reachable",
        ),
        (
            IdentifyArtifactHandler(),
            _handler_cmd(scenario, "identify", artifact_id=str(distant_artifact.id)),
            "artifact is not reachable",
        ),
        (
            AppeaseAncientBeastHandler(),
            _handler_cmd(scenario, "appease-ancient-beast", beast_id=str(distant_beast.id)),
            "ancient beast is not reachable",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(scenario, "inscribe-voice-phrase", target_id="x", word_id="y"),
            "invalid character, target, or word id",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(
                scenario,
                "inscribe-voice-phrase",
                target_id=missing,
                word_id=str(word),
                phrase="ok",
            ),
            "target does not exist",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(
                scenario,
                "inscribe-voice-phrase",
                target_id=str(distant_slate.id),
                word_id=missing,
                phrase="ok",
            ),
            "word does not exist",
        ),
        (
            InscribeVoicePhraseHandler(),
            _handler_cmd(
                scenario,
                "inscribe-voice-phrase",
                target_id=str(distant_slate.id),
                word_id=str(word),
                phrase="ok",
            ),
            "target is not reachable",
        ),
        (
            StudyVoiceInscriptionHandler(),
            _handler_cmd(scenario, "study-voice-inscription", target_id="x"),
            "invalid character or target id",
        ),
        (
            StudyVoiceInscriptionHandler(),
            _handler_cmd(scenario, "study-voice-inscription", target_id=missing),
            "target does not exist",
        ),
        (
            StudyVoiceInscriptionHandler(),
            _handler_cmd(scenario, "study-voice-inscription", target_id=str(distant_slate.id)),
            "target is not reachable",
        ),
    ]
    assert distant_guard
    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False, (reason, result.ok)
        assert result.reason == reason


def test_learn_and_cast_spell_extra_state_branches_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    character.add_component(MagicComponent(current=5, maximum=5))

    spell = spawn_entity(
        world,
        [IdentityComponent(name="No Skill Spark", kind="spell"), SpellComponent(name="No Skill")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), spell.id)

    learn = LearnSpellHandler()
    assert learn.execute(ctx, _handler_cmd(scenario, "learn-spell", spell_id=str(spell.id))).ok
    # Already learned -> rejected (line 1906).
    assert (
        learn.execute(ctx, _handler_cmd(scenario, "learn-spell", spell_id=str(spell.id))).reason
        == "spell already learned"
    )

    # Cast a learned spell with no skill_name -> no XP branch (1975 false).
    cast = CastDragonSpellHandler()
    result = cast.execute(ctx, _handler_cmd(scenario, "cast-dragon-spell", spell_id=str(spell.id)))
    assert result.ok
    assert character.get_component(MagicComponent).current == 4  # default magic_cost of 1


def test_cast_spell_with_cooldown_sets_ready_epoch_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    character.add_component(MagicComponent(current=5, maximum=5))
    spell = spawn_entity(
        world,
        [
            IdentityComponent(name="Cooldown Spark", kind="spell"),
            SpellComponent(name="Cooldown", magic_cost=1),
            SpellCooldownComponent(cooldown_seconds=20, ready_at_epoch=0),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), spell.id)
    character.add_relationship(KnowsSpell(learned_at_epoch=0), spell.id)

    result = CastDragonSpellHandler().execute(
        ctx, _handler_cmd(scenario, "cast-dragon-spell", spell_id=str(spell.id))
    )
    assert result.ok
    cooldown = world.get_entity(spell.id).get_component(SpellCooldownComponent)
    assert cooldown.ready_at_epoch == ctx.epoch + 20


def test_brew_potion_without_skill_name_skips_xp_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    recipe = spawn_entity(
        world,
        [
            IdentityComponent(name="plain recipe", kind="recipe"),
            PotionRecipeComponent(name="plain recipe", potion_name="Plain Tonic", skill_name=""),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), recipe.id)

    result = BrewPotionHandler().execute(
        ctx, _handler_cmd(scenario, "brew-potion", recipe_id=str(recipe.id))
    )
    assert result.ok
    character = world.get_entity(scenario.character)
    assert not character.has_component(SkillSetComponent)


def test_bribe_guard_branches_no_wanted_and_full_clear_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    faction = _faction(scenario)
    guard = spawn_entity(
        world,
        [
            IdentityComponent(name="Moss Guard", kind="character"),
            CharacterComponent(species="bunny"),
            GuardComponent(faction_id=str(faction), bribe_amount=10),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), guard.id)
    bribe = BribeGuardHandler()

    # No WantedComponent at all (branch 1613 false -> 1622).
    assert bribe.execute(ctx, _handler_cmd(scenario, "bribe", guard_id=str(guard.id))).ok
    assert not character.has_component(WantedComponent)

    # Wanted but for a different faction (branch 1615 false -> 1622).
    character.add_component(WantedComponent(amounts={"other_5": 7}))
    assert bribe.execute(ctx, _handler_cmd(scenario, "bribe", guard_id=str(guard.id))).ok
    assert character.get_component(WantedComponent).amounts == {"other_5": 7}

    # Bribe exactly clears the bounty to 0 -> key removed (line 1620).
    character.remove_component(WantedComponent)
    character.add_component(WantedComponent(amounts={str(faction): 10}))
    assert bribe.execute(ctx, _handler_cmd(scenario, "bribe", guard_id=str(guard.id))).ok
    assert str(faction) not in character.get_component(WantedComponent).amounts


def test_serve_jail_time_branches_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    # Sentence not complete (line 1649).
    character.add_component(JailComponent(faction_id="f1", release_epoch=ctx.epoch + 1000))
    assert (
        ServeJailTimeHandler().execute(ctx, _handler_cmd(scenario, "serve-jail-time")).reason
        == "sentence is not complete"
    )

    # Complete sentence, no WantedComponent (branch 1651 false -> 1655).
    character.remove_component(JailComponent)
    character.add_component(JailComponent(faction_id="f1", release_epoch=0))
    assert ServeJailTimeHandler().execute(ctx, _handler_cmd(scenario, "serve-jail-time")).ok
    assert not character.has_component(JailComponent)


def test_study_voice_inscription_when_word_already_known_skips_relationship():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    word = _word(scenario, name="Known Word", min_souls=0)
    # Character already knows the word (branch 2326 false).
    character.add_relationship(KnowsWord(learned_at_epoch=0), parse_entity_id(str(word)))
    slate = spawn_entity(
        world,
        [
            IdentityComponent(name="known slate", kind="prop"),
            VoiceInscriptionComponent(word_id=str(word)),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), slate.id)

    result = StudyVoiceInscriptionHandler().execute(
        ctx, _handler_cmd(scenario, "study-voice-inscription", target_id=str(slate.id))
    )
    assert result.ok
    assert str(scenario.character) in slate.get_component(VoiceInscriptionComponent).studied_by


def test_dragonsim_fragments_skip_missing_and_componentless_relationships():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    # HasPerk/KnowsWord/KnowsSpell targets that exist but lack the component
    # (the has_component branches are false).
    bare_perk = spawn_entity(world, [IdentityComponent(name="bare", kind="prop")])
    character.add_relationship(HasPerk(unlocked_at_epoch=0), bare_perk.id)
    bare_word = spawn_entity(world, [IdentityComponent(name="bare", kind="prop")])
    character.add_relationship(KnowsWord(learned_at_epoch=0), bare_word.id)
    bare_spell = spawn_entity(world, [IdentityComponent(name="bare", kind="prop")])
    character.add_relationship(KnowsSpell(learned_at_epoch=0), bare_spell.id)

    # Should not raise and should produce a list.
    assert isinstance(dragonsim_fragments(world, character), list)


def test_dragonsim_fragments_show_known_spell_and_jail():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # A known spell not present in the room (fragments lines 2390-2395).
    spell = spawn_entity(world, [SpellComponent(name="Firebolt")])
    character.add_relationship(KnowsSpell(learned_at_epoch=0), spell.id)
    # Jail fragment (line 2401).
    character.add_component(JailComponent(faction_id="f1", release_epoch=99))

    lines = dragonsim_fragments(world, character)
    assert any("Spell learned: Firebolt" in line for line in lines)
    assert any("Serving jail time for f1" in line for line in lines)


def test_cast_spell_without_skill_name_skips_xp_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    character.add_component(MagicComponent(current=5, maximum=5))
    spell = spawn_entity(
        world,
        [
            IdentityComponent(name="Wordless Spark", kind="spell"),
            SpellComponent(name="Wordless", magic_cost=2, skill_name=""),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), spell.id)
    character.add_relationship(KnowsSpell(learned_at_epoch=0), spell.id)

    # skill_name is empty -> the XP branch (1975 true) is skipped (1975 -> 1986).
    result = CastDragonSpellHandler().execute(
        ctx, _handler_cmd(scenario, "cast-dragon-spell", spell_id=str(spell.id))
    )
    assert result.ok
    assert character.get_component(MagicComponent).current == 3
    assert not character.has_component(SkillSetComponent)


def test_use_artifact_can_handle_true_for_explicit_artifact_id_key():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    use = UseArtifactHandler()
    # "artifact_id" present in payload short-circuits can_handle to True (line 2065),
    # even before the entity is looked up.
    assert use.can_handle(ctx, _handler_cmd(scenario, "use", artifact_id="entity_999")) is True
    # Falls through to the artifact-component check when only item_id is given.
    assert use.can_handle(ctx, _handler_cmd(scenario, "use", item_id="entity_999")) is False


def test_fragments_show_bounty_when_faction_key_is_non_faction_entity():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # Key parses and the entity exists, but it is not a faction (2411 -> 2413):
    # the bounty line falls back to the raw key as the faction name.
    prop = spawn_entity(world, [IdentityComponent(name="plain rock", kind="prop")])
    character.add_component(WantedComponent(amounts={str(prop.id): 8}))

    lines = dragonsim_fragments(world, character)
    assert any(f"Bounty of 8 with {prop.id}" in line for line in lines)


def test_fragments_skip_spell_component_for_already_known_nearby_spell():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    # A SpellComponent entity in the room that the character already knows: the nearby
    # SpellComponent fragment is skipped (line 2438 continue).
    known = spawn_entity(
        world,
        [IdentityComponent(name="Familiar Spark", kind="spell"), SpellComponent(name="Familiar")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), known.id)
    character.add_relationship(KnowsSpell(learned_at_epoch=0), known.id)

    lines = dragonsim_fragments(world, character)
    # The "known spell" fragment still appears, but the nearby SpellComponent is skipped.
    assert any("Spell learned: Familiar" in line for line in lines)
    assert not any("Learnable spell nearby: Familiar" in line for line in lines)
