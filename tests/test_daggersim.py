"""Tests for dagger-sim procedural RPG realm mechanics."""

from __future__ import annotations

from conftest import build_scenario
from hypothesis import given, settings
from hypothesis import strategies as st

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    ExitTo,
    IdentityComponent,
    Lane,
    PortableComponent,
    RoomComponent,
    build_submitted_command,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.components import CharacterComponent, HealthComponent
from bunnyland.core.events import CommandRejectedEvent, SpeechSaidEvent
from bunnyland.core.handlers import HandlerContext, SayHandler, TellHandler
from bunnyland.mechanics.daggersim import (
    AbandonGeneratedQuestHandler,
    AcceptGeneratedQuestHandler,
    AccountOpenedEvent,
    AfflictionContractedEvent,
    AfflictionCuredEvent,
    AfflictionIncubationProgressedEvent,
    AfflictionStigmaComponent,
    AfflictionStigmaMarkedEvent,
    AskForWorkHandler,
    AskRumorHandler,
    AttemptPacifyHandler,
    AutomapComponent,
    BankAccountComponent,
    BankComponent,
    BountyComponent,
    BountyPostedEvent,
    BuyPropertyHandler,
    BuyTravelSuppliesHandler,
    CampHandler,
    CampingComponent,
    CastSpellHandler,
    ClassTemplateComponent,
    CommitCrimeHandler,
    CompleteGeneratedQuestHandler,
    ContractAfflictionHandler,
    ConversationToneComponent,
    CourtSentenceIssuedEvent,
    CreateCustomClassHandler,
    CreateSpellHandler,
    CreatureLanguageComponent,
    CreaturePacifiedEvent,
    CrimeCommittedEvent,
    CrimeRecordComponent,
    CureAfflictionHandler,
    CureQuestHookComponent,
    CureQuestRequestedEvent,
    CustomClassComponent,
    CustomClassCreatedEvent,
    CustomSpellComponent,
    DaggerQuestRewardComponent,
    DebtCollectorComponent,
    DebtCollectorSentEvent,
    DebtComponent,
    DepositHandler,
    DialogueApproachComponent,
    DungeonComponent,
    DungeonEnteredEvent,
    DungeonExitedEvent,
    DungeonGeneratedEvent,
    DungeonObjectiveComponent,
    DungeonObjectiveFoundEvent,
    DungeonRequestedEvent,
    DungeonRoomComponent,
    DungeonRoomDiscoveredEvent,
    EnchantedItemComponent,
    EnchantedItemRechargedEvent,
    EnchantItemHandler,
    EndTransformationHandler,
    EnterDungeonHandler,
    EtiquetteSkillComponent,
    ExpandSiteHandler,
    ExpansionHookComponent,
    ExpansionRequestedEvent,
    ExtendGeneratedQuestHandler,
    FeedingNeedChangedEvent,
    FeedingNeedComponent,
    FeedingNeedConsequence,
    FeedOnHandler,
    FinePaidEvent,
    GeneratedQuestComponent,
    GeneratedSiteInstantiatedEvent,
    HostilityComponent,
    IdentifyIngredientHandler,
    IngredientComponent,
    IngredientIdentifiedEvent,
    InstitutionComponent,
    InstitutionDuesComponent,
    InstitutionDuesPaidEvent,
    InstitutionJoinedEvent,
    InstitutionPromotedEvent,
    InstitutionReputationChangedEvent,
    InstitutionReputationComponent,
    InstitutionServiceComponent,
    InstitutionServiceUsedEvent,
    InvestigateRumorHandler,
    IssueLetterOfCreditHandler,
    ItemEnchantedEvent,
    JoinInstitutionHandler,
    LanguageSkillComponent,
    LawRegionComponent,
    LeaveDungeonHandler,
    LegalReputationChangedEvent,
    LegalReputationComponent,
    LetterOfCreditComponent,
    LetterOfCreditIssuedEvent,
    LieAboutQuestHandler,
    LoanComponent,
    LoanDefaultedEvent,
    LoanDueConsequence,
    LoanIssuedEvent,
    LoanRepaidEvent,
    LodgingComponent,
    LodgingRentedEvent,
    MakePotionHandler,
    MarkAfflictionStigmaHandler,
    MarkPathHandler,
    MemberOfInstitution,
    OpenBankAccountHandler,
    OpenSecretDoorHandler,
    OwnsProperty,
    PacificationAttemptedEvent,
    PacifiedComponent,
    PayFineHandler,
    PayInstitutionDuesHandler,
    PlanTravelHandler,
    PotionMadeEvent,
    PotionMakerComponent,
    ProceduralSiteComponent,
    ProgressAfflictionIncubationHandler,
    PromoteInstitutionHandler,
    PropertyDeedComponent,
    PropertyPurchasedEvent,
    QuestAbandonedEvent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestDeadlineComponent,
    QuestDeadlineConsequence,
    QuestExtendedEvent,
    QuestFailedEvent,
    QuestGeneratedEvent,
    QuestLieToldEvent,
    QuestRefusedEvent,
    QuestTemplateComponent,
    RecallAnchorComponent,
    RecallAnchorSetEvent,
    RecallUsedEvent,
    RechargeEnchantedItemHandler,
    RechargeServiceComponent,
    RefuseGeneratedQuestHandler,
    RentLodgingHandler,
    RepayLoanHandler,
    RequestCureQuestHandler,
    RequestDungeonHandler,
    ResolveTravelInterruptionHandler,
    RestHandler,
    RestRiskComponent,
    RetrieveSafeItemHandler,
    RumorBecameExpansionEvent,
    RumorComponent,
    RumorHeardEvent,
    RumorReliabilityComponent,
    RumorTargetComponent,
    RumorVerifiedEvent,
    SafeStorageComponent,
    SafeStorageUpdatedEvent,
    SearchRoomHandler,
    SecretDoorComponent,
    SecretDoorFoundEvent,
    SendDebtCollectorHandler,
    SentenceCrimeHandler,
    ServiceAccessChangedEvent,
    ServiceAccessComponent,
    SetRecallHandler,
    SocialRegisterComponent,
    SocialRegisterReactor,
    SpellCastEvent,
    SpellCreatedEvent,
    SpellTemplateComponent,
    StoreSafeItemHandler,
    StreetwiseSkillComponent,
    SupernaturalAfflictionComponent,
    TakeLoanHandler,
    TransformationEndedEvent,
    TransformationStartedEvent,
    TransformHandler,
    TravelCompletedEvent,
    TravelCompletionConsequence,
    TravelHubComponent,
    TravelInterruptionComponent,
    TravelInterruptionResolvedEvent,
    TravelModeComponent,
    TravelPlanComponent,
    TravelRoute,
    TravelStartedEvent,
    TravelSuppliesBoughtEvent,
    UnrealizedLocationComponent,
    UseInstitutionServiceHandler,
    UseRecallHandler,
    ViewMapHandler,
    WereformComponent,
    WithdrawHandler,
    _apply_spell_effect,
    _current_law_region,
    _institution_membership,
    _name,
    _payload_entity_id,
    _rank_allows,
    _route_between,
    _selected_rumor_id,
    _service_institution,
    _string_tuple,
    daggersim_fragments,
    install_daggersim,
)
from bunnyland.mechanics.history import DeedReputationComponent
from bunnyland.prompts import ComponentPromptContext, PromptPerspective

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(ExpandSiteHandler())
    actor.register_handler(AskRumorHandler())
    actor.register_handler(InvestigateRumorHandler())
    actor.register_handler(PlanTravelHandler())
    actor.register_handler(JoinInstitutionHandler())
    actor.register_handler(UseInstitutionServiceHandler())
    actor.register_handler(AskForWorkHandler())
    actor.register_handler(AcceptGeneratedQuestHandler())
    actor.register_handler(CompleteGeneratedQuestHandler())
    actor.register_handler(OpenBankAccountHandler())
    actor.register_handler(DepositHandler())
    actor.register_handler(WithdrawHandler())
    actor.register_handler(TakeLoanHandler())
    actor.register_handler(RepayLoanHandler())
    actor.register_handler(CommitCrimeHandler())
    actor.register_handler(PayFineHandler())
    actor.register_handler(BuyPropertyHandler())
    actor.register_handler(CreateCustomClassHandler())
    actor.register_handler(CreateSpellHandler())
    actor.register_handler(EnchantItemHandler())
    actor.register_handler(CastSpellHandler())
    actor.register_handler(AttemptPacifyHandler())
    actor.register_handler(ContractAfflictionHandler())
    actor.register_handler(TransformHandler())
    actor.register_handler(FeedOnHandler())
    actor.register_handler(EndTransformationHandler())
    actor.register_handler(CureAfflictionHandler())
    actor.register_handler(RequestDungeonHandler())
    actor.register_handler(EnterDungeonHandler())
    actor.register_handler(SearchRoomHandler())
    actor.register_handler(OpenSecretDoorHandler())
    actor.register_handler(MarkPathHandler())
    actor.register_handler(ViewMapHandler())
    actor.register_handler(SetRecallHandler())
    actor.register_handler(UseRecallHandler())
    actor.register_handler(RestHandler())
    actor.register_handler(LeaveDungeonHandler())
    actor.register_consequence(TravelCompletionConsequence())
    actor.register_consequence(QuestDeadlineConsequence())
    actor.register_consequence(LoanDueConsequence())
    actor.register_consequence(FeedingNeedConsequence())


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


def _dagger_room_entity(scenario, name, kind, components):
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), *components],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


def _site(scenario):
    site = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Rain Garden Hamlet", kind="settlement"),
            ProceduralSiteComponent(site_type="hamlet", seed="rain-garden"),
            UnrealizedLocationComponent(
                summary="a damp trading stop at the edge of the moss road",
                region_id="moss-road",
            ),
            ExpansionHookComponent(trigger="rumor", generator_plugin_id="worldgen.recursive"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), site.id
    )
    return site.id


def test_daggersim_parity_handlers_mutate_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)

    institution = _dagger_room_entity(
        scenario,
        "Mages Guild",
        "institution",
        [
            InstitutionComponent(name="Mages Guild"),
            InstitutionDuesComponent(amount_due=25),
        ],
    )
    character.add_relationship(MemberOfInstitution(rank="member"), institution.id)
    refuse_quest = _dagger_room_entity(
        scenario,
        "rat cellar job",
        "quest",
        [GeneratedQuestComponent(title="rat cellar job", objective="clear rats")],
    )
    abandon_quest = _dagger_room_entity(
        scenario,
        "active job",
        "quest",
        [
            GeneratedQuestComponent(
                title="active job",
                objective="deliver",
                status="active",
                accepted_by=str(scenario.character),
            )
        ],
    )
    extend_quest = _dagger_room_entity(
        scenario,
        "timed job",
        "quest",
        [
            GeneratedQuestComponent(title="timed job", objective="return"),
            QuestDeadlineComponent(due_at_epoch=100),
        ],
    )
    lie_quest = _dagger_room_entity(
        scenario,
        "lie job",
        "quest",
        [GeneratedQuestComponent(title="lie job", objective="talk")],
    )
    bank = _dagger_room_entity(
        scenario,
        "Carrot Factors Bank",
        "bank",
        [BankComponent(name="Carrot Factors Bank")],
    )
    account = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="account", kind="bank-account"),
            BankAccountComponent(
                bank_id=str(bank.id), owner_id=str(scenario.character), balance=100
            ),
        ],
    )
    storage = _dagger_room_entity(scenario, "bank vault", "safe", [])
    carried_item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="ruby ring", kind="item"), PortableComponent(can_pick_up=True)],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried_item.id)
    debt = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="overdue loan", kind="debt"),
            DebtComponent(amount=10, defaulted_at_epoch=1),
        ],
    )
    crime = _dagger_room_entity(
        scenario,
        "trespass charge",
        "crime",
        [CrimeRecordComponent(crime_type="trespass", region_id="moss", fine=5)],
    )
    lodging = _dagger_room_entity(
        scenario,
        "road inn",
        "lodging",
        [LodgingComponent(price=5)],
    )
    interruption = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="washed out bridge", kind="travel-interruption"),
            TravelInterruptionComponent(reason="storm"),
        ],
    )
    maker = _dagger_room_entity(
        scenario,
        "guild potionmaker",
        "service",
        [PotionMakerComponent(output_item_name="tonic")],
    )
    service = _dagger_room_entity(
        scenario,
        "guild enchanter",
        "service",
        [RechargeServiceComponent(charge_amount=2)],
    )
    enchanted = _dagger_room_entity(
        scenario,
        "moss charm",
        "item",
        [EnchantedItemComponent(spell_name="Mend", effect_type="heal", magnitude=1, cost=5)],
    )
    ingredient = _dagger_room_entity(
        scenario,
        "moon sugar",
        "ingredient",
        [IngredientComponent(ingredient_name="moon sugar", effect="restore")],
    )
    character.add_component(
        SupernaturalAfflictionComponent(
            affliction_type="moon-form", contracted_at_epoch=scenario.actor.epoch
        )
    )

    calls = [
        (
            PromoteInstitutionHandler(),
            "promote-institution",
            {"institution_id": str(institution.id), "rank": "adept"},
            InstitutionPromotedEvent,
        ),
        (
            PayInstitutionDuesHandler(),
            "pay-institution-dues",
            {"institution_id": str(institution.id)},
            InstitutionDuesPaidEvent,
        ),
        (
            RefuseGeneratedQuestHandler(),
            "refuse-generated-quest",
            {"quest_id": str(refuse_quest.id)},
            QuestRefusedEvent,
        ),
        (
            AbandonGeneratedQuestHandler(),
            "abandon-generated-quest",
            {"quest_id": str(abandon_quest.id)},
            QuestAbandonedEvent,
        ),
        (
            ExtendGeneratedQuestHandler(),
            "extend-generated-quest",
            {"quest_id": str(extend_quest.id), "seconds": 50},
            QuestExtendedEvent,
        ),
        (
            LieAboutQuestHandler(),
            "lie-about-quest",
            {"quest_id": str(lie_quest.id), "lie": "done"},
            QuestLieToldEvent,
        ),
        (
            IssueLetterOfCreditHandler(),
            "issue-letter-of-credit",
            {"bank_id": str(bank.id), "amount": 30},
            LetterOfCreditIssuedEvent,
        ),
        (
            StoreSafeItemHandler(),
            "store-safe-item",
            {"storage_id": str(storage.id), "item_id": str(carried_item.id)},
            SafeStorageUpdatedEvent,
        ),
        (
            RetrieveSafeItemHandler(),
            "retrieve-safe-item",
            {"storage_id": str(storage.id), "item_id": str(carried_item.id)},
            SafeStorageUpdatedEvent,
        ),
        (
            SendDebtCollectorHandler(),
            "send-debt-collector",
            {"debt_id": str(debt.id)},
            DebtCollectorSentEvent,
        ),
        (
            SentenceCrimeHandler(),
            "sentence-crime",
            {"crime_id": str(crime.id), "sentence": "fine"},
            CourtSentenceIssuedEvent,
        ),
        (
            RentLodgingHandler(),
            "rent-lodging",
            {"lodging_id": str(lodging.id), "duration_seconds": 60},
            LodgingRentedEvent,
        ),
        (CampHandler(), "camp", {"risk": "low"}, None),
        (
            BuyTravelSuppliesHandler(),
            "buy-travel-supplies",
            {"quantity": 3},
            TravelSuppliesBoughtEvent,
        ),
        (
            ResolveTravelInterruptionHandler(),
            "resolve-travel-interruption",
            {"interruption_id": str(interruption.id)},
            TravelInterruptionResolvedEvent,
        ),
        (
            MakePotionHandler(),
            "make-potion",
            {"maker_id": str(maker.id)},
            PotionMadeEvent,
        ),
        (
            RechargeEnchantedItemHandler(),
            "recharge-enchanted-item",
            {"item_id": str(enchanted.id), "service_id": str(service.id)},
            EnchantedItemRechargedEvent,
        ),
        (
            IdentifyIngredientHandler(),
            "identify",
            {"ingredient_id": str(ingredient.id)},
            IngredientIdentifiedEvent,
        ),
        (
            ProgressAfflictionIncubationHandler(),
            "progress-affliction-incubation",
            {"stage": "active"},
            AfflictionIncubationProgressedEvent,
        ),
        (
            MarkAfflictionStigmaHandler(),
            "mark-affliction-stigma",
            {"region_id": "moss", "severity": 2},
            AfflictionStigmaMarkedEvent,
        ),
        (
            RequestCureQuestHandler(),
            "request-cure-quest",
            {"quest_id": "moon cure"},
            CureQuestRequestedEvent,
        ),
    ]

    for handler, command_type, payload, event_type in calls:
        result = handler.execute(ctx, _handler_cmd(scenario, command_type, **payload))
        assert result.ok, (command_type, result.reason)
        if event_type is not None:
            assert any(isinstance(event, event_type) for event in result.events)

    assert _institution_membership(character, institution.id).rank == "adept"
    assert str(scenario.character) in institution.get_component(InstitutionDuesComponent).paid_by
    assert refuse_quest.get_component(GeneratedQuestComponent).status == "refused"
    assert abandon_quest.get_component(GeneratedQuestComponent).status == "abandoned"
    assert extend_quest.get_component(QuestDeadlineComponent).due_at_epoch == 150
    assert lie_quest.get_component(GeneratedQuestComponent).status == "lied"
    assert account.get_component(BankAccountComponent).balance == 70
    assert storage.get_component(SafeStorageComponent).item_ids == ()
    assert crime.get_component(CrimeRecordComponent).status == "sentenced:fine"
    assert lodging.get_component(LodgingComponent).occupied_by == str(scenario.character)
    assert scenario.actor.world.get_entity(scenario.room_a).has_component(CampingComponent)
    assert interruption.get_component(TravelInterruptionComponent).resolved is True
    assert enchanted.get_component(EnchantedItemComponent).cost == 3
    assert str(scenario.character) in ingredient.get_component(IngredientComponent).identified_by
    assert character.get_component(SupernaturalAfflictionComponent).stage == "active"
    assert character.get_component(AfflictionStigmaComponent).severity == 2
    assert character.get_component(CureQuestHookComponent).quest_id == "moon cure"
    fragments = daggersim_fragments(scenario.actor.world, character)
    assert "Institution nearby: Mages Guild (guild)." in fragments
    assert "Institution dues: 25 (paid)." in fragments
    assert "Generated quest: rat cellar job (refused)." in fragments
    assert "Safe storage: 0 item(s)." in fragments
    assert "Crime record: trespass (sentenced:fine)." in fragments
    assert "Camp here: low." in fragments
    assert "Potionmaker nearby: tonic." in fragments
    assert "Recharge service nearby: +2." in fragments
    assert "Ingredient nearby: moon sugar (identified)." in fragments
    assert "Affliction: moon-form (active)." in fragments
    assert "Affliction stigma: moss severity 2." in fragments
    assert "Cure quest hook: moon-form." in fragments


def test_daggersim_parity_handlers_reject_invalid_targets_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    fake = "entity_999999"
    cases = [
        (
            PromoteInstitutionHandler(),
            "promote-institution",
            {"institution_id": fake},
            "invalid character or institution id",
            "institution does not exist",
        ),
        (
            PayInstitutionDuesHandler(),
            "pay-institution-dues",
            {"institution_id": fake},
            "invalid character or institution id",
            "institution does not exist",
        ),
        (
            RefuseGeneratedQuestHandler(),
            "refuse-generated-quest",
            {"quest_id": fake},
            "invalid character or quest id",
            "quest does not exist",
        ),
        (
            AbandonGeneratedQuestHandler(),
            "abandon-generated-quest",
            {"quest_id": fake},
            "invalid character or quest id",
            "quest does not exist",
        ),
        (
            ExtendGeneratedQuestHandler(),
            "extend-generated-quest",
            {"quest_id": fake},
            "invalid character or quest id",
            "quest does not exist",
        ),
        (
            LieAboutQuestHandler(),
            "lie-about-quest",
            {"quest_id": fake, "lie": "done"},
            "invalid character, quest, or lie",
            "quest does not exist",
        ),
        (
            IssueLetterOfCreditHandler(),
            "issue-letter-of-credit",
            {"bank_id": fake, "amount": 1},
            "invalid character or bank id",
            "bank account does not exist",
        ),
        (
            StoreSafeItemHandler(),
            "store-safe-item",
            {"storage_id": fake, "item_id": fake},
            "invalid character, storage, or item id",
            "storage or item does not exist",
        ),
        (
            RetrieveSafeItemHandler(),
            "retrieve-safe-item",
            {"storage_id": fake, "item_id": fake},
            "invalid character, storage, or item id",
            "storage or item does not exist",
        ),
        (
            SendDebtCollectorHandler(),
            "send-debt-collector",
            {"debt_id": fake},
            "invalid character or debt id",
            "debt does not exist",
        ),
        (
            SentenceCrimeHandler(),
            "sentence-crime",
            {"crime_id": fake},
            "invalid character or crime id",
            "crime record does not exist",
        ),
        (
            RentLodgingHandler(),
            "rent-lodging",
            {"lodging_id": fake},
            "invalid character or lodging id",
            "lodging does not exist",
        ),
        (
            ResolveTravelInterruptionHandler(),
            "resolve-travel-interruption",
            {"interruption_id": fake},
            "invalid character or interruption id",
            "travel interruption does not exist",
        ),
        (
            MakePotionHandler(),
            "make-potion",
            {"maker_id": fake},
            "invalid character or potion maker id",
            "potion maker does not exist",
        ),
        (
            RechargeEnchantedItemHandler(),
            "recharge-enchanted-item",
            {"item_id": fake, "service_id": fake},
            "invalid character, item, or service id",
            "item or service does not exist",
        ),
        (
            IdentifyIngredientHandler(),
            "identify",
            {"ingredient_id": fake},
            "invalid character or ingredient id",
            "ingredient does not exist",
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

    character_only_cases = [
        (CampHandler(), "camp", {}, "invalid character id"),
        (
            BuyTravelSuppliesHandler(),
            "buy-travel-supplies",
            {"quantity": 1},
            "invalid character id",
        ),
        (
            ProgressAfflictionIncubationHandler(),
            "progress-affliction-incubation",
            {},
            "invalid character id",
        ),
        (
            MarkAfflictionStigmaHandler(),
            "mark-affliction-stigma",
            {"severity": 1},
            "invalid character id",
        ),
        (RequestCureQuestHandler(), "request-cure-quest", {}, "invalid character id"),
    ]
    for handler, command_type, payload, reason in character_only_cases:
        result = handler.execute(
            ctx,
            _handler_cmd(scenario, command_type, character_id="not-an-id", **payload),
        )
        assert result.ok is False
        assert result.reason == reason

    no_affliction = ProgressAfflictionIncubationHandler().execute(
        ctx, _handler_cmd(scenario, "progress-affliction-incubation")
    )
    assert no_affliction.ok is False
    assert no_affliction.reason == "character has no supernatural affliction"
    bad_stigma = MarkAfflictionStigmaHandler().execute(
        ctx, _handler_cmd(scenario, "mark-affliction-stigma", severity=0)
    )
    assert bad_stigma.ok is False
    assert bad_stigma.reason == "stigma severity must be positive"
    no_cure = RequestCureQuestHandler().execute(ctx, _handler_cmd(scenario, "request-cure-quest"))
    assert no_cure.ok is False
    assert no_cure.reason == "character has no supernatural affliction"


def test_daggersim_parity_handlers_reject_wrong_kind_and_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    world = scenario.actor.world
    room = world.get_entity(scenario.room_a)
    character = world.get_entity(scenario.character)
    wrong_kind = spawn_entity(world, [IdentityComponent(name="plain ledger", kind="prop")])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)

    institution = spawn_entity(
        world,
        [
            IdentityComponent(name="Mages Guild", kind="institution"),
            InstitutionComponent(name="Mages Guild"),
            InstitutionDuesComponent(amount_due=10),
        ],
    )
    paid_institution = spawn_entity(
        world,
        [
            IdentityComponent(name="Paid Guild", kind="institution"),
            InstitutionComponent(name="Paid Guild"),
            InstitutionDuesComponent(amount_due=10, paid_by=(str(scenario.character),)),
        ],
    )
    no_dues_institution = spawn_entity(
        world,
        [
            IdentityComponent(name="Free Guild", kind="institution"),
            InstitutionComponent(name="Free Guild"),
            InstitutionDuesComponent(amount_due=0),
        ],
    )
    for entity in (institution, paid_institution, no_dues_institution):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    character.add_relationship(
        MemberOfInstitution(rank="member", since_epoch=0), paid_institution.id
    )
    character.add_relationship(
        MemberOfInstitution(rank="member", since_epoch=0), no_dues_institution.id
    )

    offered_quest = spawn_entity(
        world,
        [
            IdentityComponent(name="offered job", kind="quest"),
            GeneratedQuestComponent(title="job", objective="work"),
        ],
    )
    active_quest = spawn_entity(
        world,
        [
            IdentityComponent(name="active job", kind="quest"),
            GeneratedQuestComponent(
                title="active job",
                objective="work",
                status="active",
                accepted_by=str(scenario.character),
            ),
            QuestDeadlineComponent(due_at_epoch=10),
        ],
    )
    no_deadline_quest = spawn_entity(
        world,
        [
            IdentityComponent(name="timeless job", kind="quest"),
            GeneratedQuestComponent(title="job", objective="work"),
        ],
    )
    for entity in (offered_quest, active_quest, no_deadline_quest):
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), entity.id)

    bank = spawn_entity(
        world,
        [IdentityComponent(name="bank", kind="bank"), BankComponent(name="bank")],
    )
    poor_account = spawn_entity(
        world,
        [
            IdentityComponent(name="poor account", kind="bank-account"),
            BankAccountComponent(owner_id=str(scenario.character), bank_id=str(bank.id), balance=1),
        ],
    )
    storage = spawn_entity(
        world,
        [
            IdentityComponent(name="safe", kind="safe"),
            SafeStorageComponent(owner_id=str(scenario.character)),
        ],
    )
    other_storage = spawn_entity(
        world,
        [IdentityComponent(name="other safe", kind="safe"), SafeStorageComponent(owner_id="other")],
    )
    carried_item = spawn_entity(
        world,
        [IdentityComponent(name="coin", kind="item"), PortableComponent(can_pick_up=True)],
    )
    loose_item = spawn_entity(
        world,
        [IdentityComponent(name="loose coin", kind="item"), PortableComponent(can_pick_up=True)],
    )
    for entity in (bank, storage, other_storage, loose_item):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried_item.id)

    debt = spawn_entity(
        world,
        [
            IdentityComponent(name="debt", kind="debt"),
            DebtComponent(amount=5, defaulted_at_epoch=0),
        ],
    )
    crime = spawn_entity(
        world,
        [
            IdentityComponent(name="charge", kind="crime"),
            CrimeRecordComponent(crime_type="trespass", region_id="moss", fine=5),
        ],
    )
    lodging = spawn_entity(
        world,
        [IdentityComponent(name="room", kind="lodging"), LodgingComponent(occupied_by="other")],
    )
    distant_lodging = spawn_entity(world, [LodgingComponent()])
    interruption = spawn_entity(
        world,
        [
            IdentityComponent(name="ambush", kind="travel-interruption"),
            TravelInterruptionComponent(reason="ambush", resolved=True),
        ],
    )
    maker = spawn_entity(
        world,
        [IdentityComponent(name="maker", kind="service"), PotionMakerComponent()],
    )
    distant_maker = spawn_entity(world, [PotionMakerComponent()])
    enchanted = spawn_entity(
        world,
        [
            IdentityComponent(name="wand", kind="item"),
            EnchantedItemComponent(spell_name="spark", effect_type="harm", magnitude=1, cost=5),
        ],
    )
    service = spawn_entity(
        world,
        [IdentityComponent(name="recharge", kind="service"), RechargeServiceComponent()],
    )
    distant_service = spawn_entity(world, [RechargeServiceComponent()])
    ingredient = spawn_entity(
        world,
        [
            IdentityComponent(name="moon sugar", kind="ingredient"),
            IngredientComponent(ingredient_name="moon sugar"),
        ],
    )
    identified_ingredient = spawn_entity(
        world,
        [
            IdentityComponent(name="known sugar", kind="ingredient"),
            IngredientComponent(
                ingredient_name="known sugar",
                identified_by=(str(scenario.character),),
            ),
        ],
    )
    distant_ingredient = spawn_entity(world, [IngredientComponent(ingredient_name="far herb")])
    for entity in (
        debt,
        crime,
        lodging,
        interruption,
        maker,
        enchanted,
        service,
        ingredient,
        identified_ingredient,
    ):
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)

    cases = [
        (
            PromoteInstitutionHandler(),
            _handler_cmd(scenario, "promote-institution", institution_id=str(institution.id)),
            "not an institution member",
        ),
        (
            PayInstitutionDuesHandler(),
            _handler_cmd(scenario, "pay-institution-dues", institution_id=str(institution.id)),
            "not an institution member",
        ),
        (
            PayInstitutionDuesHandler(),
            _handler_cmd(
                scenario,
                "pay-institution-dues",
                institution_id=str(no_dues_institution.id),
            ),
            "no dues are owed",
        ),
        (
            PayInstitutionDuesHandler(),
            _handler_cmd(
                scenario,
                "pay-institution-dues",
                institution_id=str(paid_institution.id),
            ),
            "dues already paid",
        ),
        (
            RefuseGeneratedQuestHandler(),
            _handler_cmd(scenario, "refuse-generated-quest", quest_id=str(wrong_kind.id)),
            "target is not a generated quest",
        ),
        (
            RefuseGeneratedQuestHandler(),
            _handler_cmd(scenario, "refuse-generated-quest", quest_id=str(active_quest.id)),
            "quest is not offered",
        ),
        (
            AbandonGeneratedQuestHandler(),
            _handler_cmd(scenario, "abandon-generated-quest", quest_id=str(wrong_kind.id)),
            "target is not a generated quest",
        ),
        (
            AbandonGeneratedQuestHandler(),
            _handler_cmd(scenario, "abandon-generated-quest", quest_id=str(offered_quest.id)),
            "quest is not active for character",
        ),
        (
            ExtendGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "extend-generated-quest",
                quest_id=str(active_quest.id),
                seconds=0,
            ),
            "extension must be positive",
        ),
        (
            ExtendGeneratedQuestHandler(),
            _handler_cmd(scenario, "extend-generated-quest", quest_id=str(wrong_kind.id)),
            "target is not a generated quest",
        ),
        (
            ExtendGeneratedQuestHandler(),
            _handler_cmd(scenario, "extend-generated-quest", quest_id=str(no_deadline_quest.id)),
            "quest has no deadline",
        ),
        (
            LieAboutQuestHandler(),
            _handler_cmd(
                scenario,
                "lie-about-quest",
                quest_id=str(wrong_kind.id),
                lie="done",
            ),
            "target is not a generated quest",
        ),
        (
            IssueLetterOfCreditHandler(),
            _handler_cmd(scenario, "issue-letter-of-credit", bank_id=str(bank.id), amount=0),
            "letter amount must be positive",
        ),
        (
            IssueLetterOfCreditHandler(),
            _handler_cmd(scenario, "issue-letter-of-credit", bank_id=str(bank.id), amount=2),
            "insufficient bank balance",
        ),
        (
            StoreSafeItemHandler(),
            _handler_cmd(
                scenario,
                "store-safe-item",
                storage_id=str(storage.id),
                item_id=str(loose_item.id),
            ),
            "item is not carried",
        ),
        (
            StoreSafeItemHandler(),
            _handler_cmd(
                scenario,
                "store-safe-item",
                storage_id=str(other_storage.id),
                item_id=str(carried_item.id),
            ),
            "safe storage belongs to someone else",
        ),
        (
            RetrieveSafeItemHandler(),
            _handler_cmd(
                scenario,
                "retrieve-safe-item",
                storage_id=str(wrong_kind.id),
                item_id=str(loose_item.id),
            ),
            "target is not safe storage",
        ),
        (
            RetrieveSafeItemHandler(),
            _handler_cmd(
                scenario,
                "retrieve-safe-item",
                storage_id=str(other_storage.id),
                item_id=str(loose_item.id),
            ),
            "safe storage belongs to someone else",
        ),
        (
            RetrieveSafeItemHandler(),
            _handler_cmd(
                scenario,
                "retrieve-safe-item",
                storage_id=str(storage.id),
                item_id=str(loose_item.id),
            ),
            "item is not in safe storage",
        ),
        (
            SendDebtCollectorHandler(),
            _handler_cmd(scenario, "send-debt-collector", debt_id=str(wrong_kind.id)),
            "target is not debt",
        ),
        (
            SentenceCrimeHandler(),
            _handler_cmd(scenario, "sentence-crime", crime_id=str(wrong_kind.id)),
            "target is not a crime record",
        ),
        (
            RentLodgingHandler(),
            _handler_cmd(scenario, "rent-lodging", lodging_id=str(lodging.id), duration_seconds=0),
            "lodging duration must be positive",
        ),
        (
            RentLodgingHandler(),
            _handler_cmd(scenario, "rent-lodging", lodging_id=str(distant_lodging.id)),
            "lodging is not reachable",
        ),
        (
            RentLodgingHandler(),
            _handler_cmd(scenario, "rent-lodging", lodging_id=str(wrong_kind.id)),
            "target is not lodging",
        ),
        (
            RentLodgingHandler(),
            _handler_cmd(scenario, "rent-lodging", lodging_id=str(lodging.id)),
            "lodging is occupied",
        ),
        (
            BuyTravelSuppliesHandler(),
            _handler_cmd(scenario, "buy-travel-supplies", quantity=0),
            "supply quantity must be positive",
        ),
        (
            ResolveTravelInterruptionHandler(),
            _handler_cmd(
                scenario,
                "resolve-travel-interruption",
                interruption_id=str(wrong_kind.id),
            ),
            "target is not a travel interruption",
        ),
        (
            ResolveTravelInterruptionHandler(),
            _handler_cmd(
                scenario,
                "resolve-travel-interruption",
                interruption_id=str(interruption.id),
            ),
            "travel interruption is already resolved",
        ),
        (
            MakePotionHandler(),
            _handler_cmd(scenario, "make-potion", maker_id=str(distant_maker.id)),
            "potion maker is not reachable",
        ),
        (
            MakePotionHandler(),
            _handler_cmd(scenario, "make-potion", maker_id=str(wrong_kind.id)),
            "target is not a potion maker",
        ),
        (
            RechargeEnchantedItemHandler(),
            _handler_cmd(
                scenario,
                "recharge-enchanted-item",
                item_id=str(enchanted.id),
                service_id=str(distant_service.id),
            ),
            "item or service is not reachable",
        ),
        (
            RechargeEnchantedItemHandler(),
            _handler_cmd(
                scenario,
                "recharge-enchanted-item",
                item_id=str(wrong_kind.id),
                service_id=str(service.id),
            ),
            "target item is not enchanted",
        ),
        (
            RechargeEnchantedItemHandler(),
            _handler_cmd(
                scenario,
                "recharge-enchanted-item",
                item_id=str(enchanted.id),
                service_id=str(wrong_kind.id),
            ),
            "target is not a recharge service",
        ),
        (
            IdentifyIngredientHandler(),
            _handler_cmd(scenario, "identify", ingredient_id=str(distant_ingredient.id)),
            "ingredient is not reachable",
        ),
        (
            IdentifyIngredientHandler(),
            _handler_cmd(scenario, "identify", ingredient_id=str(wrong_kind.id)),
            "target is not an ingredient",
        ),
        (
            IdentifyIngredientHandler(),
            _handler_cmd(
                scenario,
                "identify",
                ingredient_id=str(identified_ingredient.id),
            ),
            "ingredient already identified",
        ),
    ]

    assert poor_account.has_component(BankAccountComponent)
    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def _rumor(scenario, site_id, *, reliability=1.0):
    rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="carrot vault rumor", kind="rumor"),
            RumorComponent(text="The old carrot vault beneath Rain Garden still exists."),
            RumorReliabilityComponent(score=reliability),
            RumorTargetComponent(target_id=str(site_id)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rumor.id
    )
    return rumor.id


def _travel_route(scenario, *, travel_seconds=2 * HOUR):
    origin = scenario.actor.world.get_entity(scenario.room_a)
    destination = scenario.actor.world.get_entity(scenario.room_b)
    origin.add_component(TravelHubComponent(name="Mosslit Burrow", region_id="moss-road"))
    destination.add_component(TravelHubComponent(name="North Tunnel", region_id="moss-road"))
    origin.add_relationship(
        TravelRoute(travel_seconds=travel_seconds, label="moss road"),
        scenario.room_b,
    )


def _institution(
    scenario,
    *,
    required_rank="member",
    required_deed_tag="",
    required_deed_score=0.0,
):
    institution = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Burrow Cartographers", kind="institution"),
            InstitutionComponent(name="Burrow Cartographers", institution_type="guild"),
        ],
    )
    service = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="local map service", kind="service"),
            InstitutionServiceComponent(
                service_name="local map",
                required_rank=required_rank,
                output_item_name="moss road map",
                required_deed_tag=required_deed_tag,
                required_deed_score=required_deed_score,
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), institution.id
    )
    institution.add_relationship(Contains(mode=ContainmentMode.CONTAINER), service.id)
    return institution.id, service.id


def _quest_template(scenario, *, duration_seconds=10 * HOUR):
    template = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ratcatcher errand", kind="quest-template"),
            QuestTemplateComponent(
                title="Clear the North Tunnel",
                objective="Drive the rats away from the old milestone.",
                reward_item_name="guild writ",
                duration_seconds=duration_seconds,
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), template.id
    )
    return template.id


def _bank(scenario):
    bank = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Carrot Factors Bank", kind="bank"),
            BankComponent(name="Carrot Factors Bank", region_id="moss-road"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), bank.id
    )
    return bank.id


def _property(scenario, *, price=15):
    property_entity = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moss Road Cottage", kind="property"),
            PropertyDeedComponent(region_id="moss-road", price=price),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), property_entity.id
    )
    return property_entity.id


def _law_region(scenario):
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        LawRegionComponent(region_id="moss-road", fines={"trespass": 15, "default": 10})
    )


def _class_template(scenario):
    template = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moonlit Forager template", kind="class-template"),
            ClassTemplateComponent(
                class_name="Moonlit Forager",
                primary_skills=("foraging", "stealth", "gardening"),
                major_skills=("cooking", "animal speech", "memory"),
                minor_skills=("etiquette", "knife", "weather lore"),
                advantages=("night vision",),
                disadvantages=("heat weakness",),
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), template.id
    )
    return template.id


def _spell_template(scenario):
    template = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="mend sprout formula", kind="spell-template"),
            SpellTemplateComponent(
                spell_name="Mend Sprout",
                effect_type="heal",
                magnitude=4.0,
                cost=1,
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), template.id
    )
    return template.id


def test_daggersim_small_helpers_cover_default_branches():
    scenario = build_scenario()
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    nameless = spawn_entity(world, [])

    assert _name(nameless) == str(nameless.id)
    assert _string_tuple(7, ("fallback",)) == ("fallback",)
    assert _current_law_region(world, nameless) is None
    assert _route_between(world.get_entity(scenario.room_a), scenario.room_b) is None
    assert _service_institution(world, nameless) is None
    assert _institution_membership(character, scenario.room_b) is None
    assert _rank_allows("guest", "master") is False
    assert _rank_allows("custom", "custom") is True

    rumor = spawn_entity(
        world,
        [
            IdentityComponent(name="unheard rumor", kind="rumor"),
            RumorComponent(text="A hidden cellar remains."),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rumor.id
    )

    assert _selected_rumor_id(ctx, scenario.character, None) == rumor.id


def _hostile_creature(scenario):
    creature = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="moon moth", kind="creature"),
            CreatureLanguageComponent(language="Mothwing", pacification_difficulty=2),
            HostilityComponent(hostile=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), creature.id
    )
    return creature.id


async def test_expand_site_instantiates_unrealized_location():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    requested: list[ExpansionRequestedEvent] = []
    instantiated: list[GeneratedSiteInstantiatedEvent] = []
    scenario.actor.bus.subscribe(ExpansionRequestedEvent, requested.append)
    scenario.actor.bus.subscribe(GeneratedSiteInstantiatedEvent, instantiated.append)

    await scenario.actor.submit(_cmd(scenario, "expand-site", site_id=str(site_id)))
    await scenario.actor.tick(HOUR)

    site = scenario.actor.world.get_entity(site_id)
    procedural = site.get_component(ProceduralSiteComponent)
    unrealized = site.get_component(UnrealizedLocationComponent)
    assert procedural.generated is True
    assert procedural.generator_id == "worldgen.recursive"
    assert unrealized.detail_level == "instantiated"
    assert requested[0].trigger == "rumor"
    assert instantiated[0].site_type == "hamlet"


async def test_expand_site_rejects_already_instantiated_location():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "expand-site", site_id=str(site_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "expand-site", site_id=str(site_id)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "site is already instantiated" for event in rejects)


async def test_heard_rumor_can_be_verified_into_expansion_request():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    rumor_id = _rumor(scenario, site_id)
    heard: list[RumorHeardEvent] = []
    verified: list[RumorVerifiedEvent] = []
    seeded: list[RumorBecameExpansionEvent] = []
    requested: list[ExpansionRequestedEvent] = []
    scenario.actor.bus.subscribe(RumorHeardEvent, heard.append)
    scenario.actor.bus.subscribe(RumorVerifiedEvent, verified.append)
    scenario.actor.bus.subscribe(RumorBecameExpansionEvent, seeded.append)
    scenario.actor.bus.subscribe(ExpansionRequestedEvent, requested.append)

    await scenario.actor.submit(_cmd(scenario, "ask-rumor", rumor_id=str(rumor_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "investigate-rumor", rumor_id=str(rumor_id))
    )
    await scenario.actor.tick(HOUR)

    rumor = scenario.actor.world.get_entity(rumor_id).get_component(RumorComponent)
    assert str(scenario.character) in rumor.heard_by
    assert rumor.state == "verified"
    assert heard[0].text.startswith("The old carrot vault")
    assert verified[0].rumor_id == str(rumor_id)
    assert seeded[0].site_id == str(site_id)
    assert requested[-1].trigger == "rumor"
    assert requested[-1].site_id == str(site_id)


async def test_false_rumor_is_disproven_without_expansion_request():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    rumor_id = _rumor(scenario, site_id, reliability=0.0)
    requested: list[ExpansionRequestedEvent] = []
    scenario.actor.bus.subscribe(ExpansionRequestedEvent, requested.append)

    await scenario.actor.submit(_cmd(scenario, "ask-rumor", rumor_id=str(rumor_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "investigate-rumor", rumor_id=str(rumor_id))
    )
    await scenario.actor.tick(HOUR)

    rumor = scenario.actor.world.get_entity(rumor_id).get_component(RumorComponent)
    assert rumor.state == "disproven"
    assert requested == []


def test_investigate_rumor_rejects_invalid_targets_and_states():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    rumor_id = _rumor(scenario, site_id)
    object_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="notice board", kind="prop")],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), object_id
    )
    distant_rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant rumor", kind="rumor"),
            RumorComponent(text="A far-off story."),
        ],
    )
    resolved_rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="resolved rumor", kind="rumor"),
            RumorComponent(
                text="This one is settled.",
                heard_by=(str(scenario.character),),
                state="verified",
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), resolved_rumor.id
    )
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    handler = InvestigateRumorHandler()

    cases = [
        (
            _handler_cmd(
                scenario,
                "investigate-rumor",
                character_id="not-an-id",
                rumor_id=str(rumor_id),
            ),
            "invalid character or rumor id",
        ),
        (
            _handler_cmd(scenario, "investigate-rumor", rumor_id="entity_999"),
            "rumor does not exist",
        ),
        (
            _handler_cmd(scenario, "investigate-rumor", rumor_id=str(distant_rumor.id)),
            "rumor is not reachable",
        ),
        (
            _handler_cmd(scenario, "investigate-rumor", rumor_id=str(object_id)),
            "target is not a rumor",
        ),
        (
            _handler_cmd(scenario, "investigate-rumor", rumor_id=str(rumor_id)),
            "rumor has not been heard",
        ),
        (
            _handler_cmd(scenario, "investigate-rumor", rumor_id=str(resolved_rumor.id)),
            "rumor is already resolved",
        ),
    ]

    for command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_expand_ask_rumor_and_travel_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong_kind_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="notice board", kind="prop")],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind_id
    )
    distant_site = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant ruin", kind="site"),
            ProceduralSiteComponent(site_type="ruin", seed="far"),
            UnrealizedLocationComponent(summary="too far away", region_id="moss-road"),
        ],
    )
    realized_site = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="realized camp", kind="site"),
            ProceduralSiteComponent(site_type="camp", seed="realized"),
        ],
    )
    instantiated_site = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="instantiated camp", kind="site"),
            ProceduralSiteComponent(site_type="camp", seed="instantiated", generated=True),
            UnrealizedLocationComponent(
                summary="already here",
                region_id="moss-road",
                detail_level="instantiated",
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), realized_site.id
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), instantiated_site.id
    )
    distant_rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant rumor", kind="rumor"),
            RumorComponent(text="Too far away."),
        ],
    )
    heard_rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="heard rumor", kind="rumor"),
            RumorComponent(text="Already heard.", heard_by=(str(scenario.character),)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), heard_rumor.id
    )

    cases = [
        (
            ExpandSiteHandler(),
            _handler_cmd(scenario, "expand-site", site_id="entity_999"),
            "site does not exist",
        ),
        (
            ExpandSiteHandler(),
            _handler_cmd(scenario, "expand-site", site_id=str(distant_site.id)),
            "site is not reachable",
        ),
        (
            ExpandSiteHandler(),
            _handler_cmd(scenario, "expand-site", site_id=str(wrong_kind_id)),
            "target is not a procedural site",
        ),
        (
            ExpandSiteHandler(),
            _handler_cmd(scenario, "expand-site", site_id=str(realized_site.id)),
            "target is already realized",
        ),
        (
            ExpandSiteHandler(),
            _handler_cmd(scenario, "expand-site", site_id=str(instantiated_site.id)),
            "site is already instantiated",
        ),
        (
            AskRumorHandler(),
            _handler_cmd(scenario, "ask-rumor", rumor_id=str(distant_rumor.id)),
            "rumor is not reachable",
        ),
        (
            AskRumorHandler(),
            _handler_cmd(scenario, "ask-rumor", rumor_id=str(wrong_kind_id)),
            "target is not a rumor",
        ),
        (
            AskRumorHandler(),
            _handler_cmd(scenario, "ask-rumor", rumor_id=str(heard_rumor.id)),
            "rumor already heard",
        ),
        (
            PlanTravelHandler(),
            _handler_cmd(scenario, "plan-travel", destination_id="entity_999"),
            "destination does not exist",
        ),
        (
            PlanTravelHandler(),
            _handler_cmd(scenario, "plan-travel", destination_id=str(scenario.room_b)),
            "origin is not a travel hub",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    no_rumor_scenario = build_scenario()
    no_rumor_ctx = HandlerContext(
        no_rumor_scenario.actor.world,
        no_rumor_scenario.actor.epoch,
    )
    result = AskRumorHandler().execute(
        no_rumor_ctx,
        _handler_cmd(no_rumor_scenario, "ask-rumor"),
    )
    assert result.ok is False
    assert result.reason == "rumor does not exist"

    traveling_scenario = build_scenario()
    traveling_character = traveling_scenario.actor.world.get_entity(
        traveling_scenario.character
    )
    traveling_character.add_component(
        TravelPlanComponent(
            destination_id=str(traveling_scenario.room_b),
            started_at_epoch=0,
            arrive_at_epoch=HOUR,
        )
    )
    result = PlanTravelHandler().execute(
        HandlerContext(traveling_scenario.actor.world, traveling_scenario.actor.epoch),
        _handler_cmd(
            traveling_scenario,
            "plan-travel",
            destination_id=str(traveling_scenario.room_b),
        ),
    )
    assert result.ok is False
    assert result.reason == "character is already traveling"

    detached_scenario = build_scenario()
    detached_scenario.actor.world.get_entity(detached_scenario.room_a).remove_relationship(
        Contains,
        detached_scenario.character,
    )
    result = PlanTravelHandler().execute(
        HandlerContext(detached_scenario.actor.world, detached_scenario.actor.epoch),
        _handler_cmd(
            detached_scenario,
            "plan-travel",
            destination_id=str(detached_scenario.room_b),
        ),
    )
    assert result.ok is False
    assert result.reason == "character is not at a travel hub"

    no_route_scenario = build_scenario()
    no_route_scenario.actor.world.get_entity(no_route_scenario.room_a).add_component(
        TravelHubComponent(name="Origin", region_id="moss-road")
    )
    result = PlanTravelHandler().execute(
        HandlerContext(no_route_scenario.actor.world, no_route_scenario.actor.epoch),
        _handler_cmd(
            no_route_scenario,
            "plan-travel",
            destination_id=str(no_route_scenario.room_b),
        ),
    )
    assert result.ok is False
    assert result.reason == "destination is not a travel hub"

    no_route_scenario.actor.world.get_entity(no_route_scenario.room_b).add_component(
        TravelHubComponent(name="Destination", region_id="moss-road")
    )
    result = PlanTravelHandler().execute(
        HandlerContext(no_route_scenario.actor.world, no_route_scenario.actor.epoch),
        _handler_cmd(
            no_route_scenario,
            "plan-travel",
            destination_id=str(no_route_scenario.room_b),
        ),
    )
    assert result.ok is False
    assert result.reason == "no travel route to destination"


def test_travel_completion_covers_pending_invalid_and_originless_plans():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    consequence = TravelCompletionConsequence()

    character.add_component(
        TravelPlanComponent(
            destination_id=str(scenario.room_b),
            started_at_epoch=0,
            arrive_at_epoch=HOUR,
            mode="walking",
            route_label="moss road",
        )
    )
    assert consequence.process(scenario.actor.world, HOUR - 1) == []

    replace_component(
        character,
        TravelPlanComponent(
            destination_id="not-an-entity",
            started_at_epoch=0,
            arrive_at_epoch=HOUR,
            mode="walking",
            route_label="moss road",
        ),
    )
    assert consequence.process(scenario.actor.world, HOUR) == []

    replace_component(
        character,
        TravelPlanComponent(
            destination_id=str(scenario.room_b),
            started_at_epoch=0,
            arrive_at_epoch=HOUR,
            mode="walking",
            route_label="moss road",
        ),
    )
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )

    events = consequence.process(scenario.actor.world, HOUR)

    assert len(events) == 1
    assert isinstance(events[0], TravelCompletedEvent)
    assert container_of(character) == scenario.room_b


def test_daggersim_institution_quest_and_bank_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    wrong_kind_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="notice board", kind="prop")],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind_id
    )
    distant_institution = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Distant Guild", kind="institution"),
            InstitutionComponent(name="Distant Guild", institution_type="guild"),
        ],
    )
    distant_service = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant service", kind="service"),
            InstitutionServiceComponent(service_name="distant"),
        ],
    )
    distant_institution.add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), distant_service.id
    )
    institution_id, service_id = _institution(scenario, required_rank="officer")
    loose_service = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="loose service", kind="service"),
            InstitutionServiceComponent(service_name="loose"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), loose_service.id
    )
    bad_parent_service = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bad parent service", kind="service"),
            InstitutionServiceComponent(service_name="bad parent"),
        ],
    )
    wrong_parent = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="counter", kind="prop")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_parent.id
    )
    wrong_parent.add_relationship(Contains(mode=ContainmentMode.CONTAINER), bad_parent_service.id)
    _quest_template(scenario)
    distant_template = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far errand", kind="quest-template"),
            QuestTemplateComponent(
                title="Far Errand",
                objective="Go far",
                reward_item_name="far writ",
            ),
        ],
    )
    distant_offered_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant offered quest", kind="quest"),
            GeneratedQuestComponent(title="Distant Offered", objective="Help"),
        ],
    )
    distant_active_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant active quest", kind="quest"),
            GeneratedQuestComponent(
                title="Distant Active",
                objective="Help",
                status="active",
                accepted_by=str(scenario.character),
            ),
        ],
    )
    offered_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="offered quest", kind="quest"),
            GeneratedQuestComponent(title="Offered", objective="Help"),
        ],
    )
    active_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="active quest", kind="quest"),
            GeneratedQuestComponent(
                title="Active",
                objective="Help",
                status="active",
                accepted_by=str(scenario.character),
            ),
            DaggerQuestRewardComponent(item_name="writ"),
        ],
    )
    completed_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="completed quest", kind="quest"),
            GeneratedQuestComponent(title="Done", objective="Help", status="completed"),
        ],
    )
    no_reward_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="rewardless quest", kind="quest"),
            GeneratedQuestComponent(
                title="Rewardless",
                objective="Help",
                status="active",
                accepted_by=str(scenario.character),
            ),
        ],
    )
    late_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="late quest", kind="quest"),
            GeneratedQuestComponent(
                title="Late",
                objective="Help",
                status="active",
                accepted_by=str(scenario.character),
            ),
            QuestDeadlineComponent(due_at_epoch=scenario.actor.epoch - 1),
            DaggerQuestRewardComponent(item_name="late writ"),
        ],
    )
    other_character_quest = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="other character quest", kind="quest"),
            GeneratedQuestComponent(
                title="Other Character",
                objective="Help",
                status="active",
                accepted_by="entity_999",
            ),
            DaggerQuestRewardComponent(item_name="other writ"),
        ],
    )
    for quest_id in (
        offered_quest.id,
        active_quest.id,
        completed_quest.id,
        no_reward_quest.id,
        late_quest.id,
        other_character_quest.id,
    ):
        scenario.actor.world.get_entity(scenario.room_a).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), quest_id
        )
    bank_id = _bank(scenario)
    distant_bank = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Bank", kind="bank"),
            BankComponent(name="Far Bank", region_id="moss-road"),
        ],
    )
    account = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bank account", kind="bank-account"),
            BankAccountComponent(bank_id=str(bank_id), owner_id=str(scenario.character)),
        ],
    )

    cases = [
        (
            JoinInstitutionHandler(),
            _handler_cmd(scenario, "join-institution", institution_id="entity_999"),
            "institution does not exist",
        ),
        (
            JoinInstitutionHandler(),
            _handler_cmd(
                scenario,
                "join-institution",
                institution_id=str(distant_institution.id),
            ),
            "institution is not reachable",
        ),
        (
            JoinInstitutionHandler(),
            _handler_cmd(scenario, "join-institution", institution_id=str(wrong_kind_id)),
            "target is not an institution",
        ),
        (
            UseInstitutionServiceHandler(),
            _handler_cmd(scenario, "use-institution-service", service_id="entity_999"),
            "service does not exist",
        ),
        (
            UseInstitutionServiceHandler(),
            _handler_cmd(
                scenario,
                "use-institution-service",
                service_id=str(distant_service.id),
            ),
            "service is not reachable",
        ),
        (
            UseInstitutionServiceHandler(),
            _handler_cmd(
                scenario,
                "use-institution-service",
                service_id=str(wrong_kind_id),
            ),
            "target is not an institution service",
        ),
        (
            UseInstitutionServiceHandler(),
            _handler_cmd(
                scenario,
                "use-institution-service",
                service_id=str(loose_service.id),
            ),
            "service institution is invalid",
        ),
        (
            UseInstitutionServiceHandler(),
            _handler_cmd(
                scenario,
                "use-institution-service",
                service_id=str(bad_parent_service.id),
            ),
            "service institution is invalid",
        ),
        (
            UseInstitutionServiceHandler(),
            _handler_cmd(scenario, "use-institution-service", service_id=str(service_id)),
            "not an institution member",
        ),
        (
            AskForWorkHandler(),
            _handler_cmd(scenario, "ask-for-work", template_id="entity_999"),
            "quest template does not exist",
        ),
        (
            AskForWorkHandler(),
            _handler_cmd(
                scenario,
                "ask-for-work",
                template_id=str(distant_template.id),
            ),
            "quest template is not reachable",
        ),
        (
            AskForWorkHandler(),
            _handler_cmd(scenario, "ask-for-work", template_id=str(wrong_kind_id)),
            "target is not a quest template",
        ),
        (
            AcceptGeneratedQuestHandler(),
            _handler_cmd(scenario, "accept-generated-quest", quest_id="entity_999"),
            "quest does not exist",
        ),
        (
            AcceptGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "accept-generated-quest",
                quest_id=str(distant_offered_quest.id),
            ),
            "quest is not reachable",
        ),
        (
            AcceptGeneratedQuestHandler(),
            _handler_cmd(scenario, "accept-generated-quest", quest_id=str(wrong_kind_id)),
            "target is not a generated quest",
        ),
        (
            AcceptGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "accept-generated-quest",
                quest_id=str(completed_quest.id),
            ),
            "quest is not offered",
        ),
        (
            CompleteGeneratedQuestHandler(),
            _handler_cmd(scenario, "complete-generated-quest", quest_id="entity_999"),
            "quest does not exist",
        ),
        (
            CompleteGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "complete-generated-quest",
                quest_id=str(distant_active_quest.id),
            ),
            "quest is not reachable",
        ),
        (
            CompleteGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "complete-generated-quest",
                quest_id=str(wrong_kind_id),
            ),
            "target is not a generated quest",
        ),
        (
            CompleteGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "complete-generated-quest",
                quest_id=str(offered_quest.id),
            ),
            "quest is not active",
        ),
        (
            CompleteGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "complete-generated-quest",
                quest_id=str(other_character_quest.id),
            ),
            "quest is not accepted by character",
        ),
        (
            CompleteGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "complete-generated-quest",
                quest_id=str(late_quest.id),
            ),
            "quest deadline has passed",
        ),
        (
            CompleteGeneratedQuestHandler(),
            _handler_cmd(
                scenario,
                "complete-generated-quest",
                quest_id=str(no_reward_quest.id),
            ),
            "quest has no reward",
        ),
        (
            OpenBankAccountHandler(),
            _handler_cmd(scenario, "open-bank-account", bank_id="entity_999"),
            "bank does not exist",
        ),
        (
            OpenBankAccountHandler(),
            _handler_cmd(
                scenario,
                "open-bank-account",
                bank_id=str(distant_bank.id),
            ),
            "bank is not reachable",
        ),
        (
            OpenBankAccountHandler(),
            _handler_cmd(scenario, "open-bank-account", bank_id=str(wrong_kind_id)),
            "target is not a bank",
        ),
        (
            DepositHandler(),
            _handler_cmd(scenario, "deposit", bank_id=str(bank_id), amount=0),
            "deposit amount must be positive",
        ),
        (
            DepositHandler(),
            _handler_cmd(scenario, "deposit", bank_id=str(scenario.room_b), amount=1),
            "bank account does not exist",
        ),
        (
            WithdrawHandler(),
            _handler_cmd(scenario, "withdraw", bank_id=str(bank_id), amount=0),
            "withdrawal amount must be positive",
        ),
        (
            WithdrawHandler(),
            _handler_cmd(scenario, "withdraw", bank_id=str(scenario.room_b), amount=1),
            "bank account does not exist",
        ),
        (
            TakeLoanHandler(),
            _handler_cmd(scenario, "take-loan", bank_id=str(bank_id), amount=0),
            "loan amount must be positive",
        ),
        (
            TakeLoanHandler(),
            _handler_cmd(scenario, "take-loan", bank_id=str(scenario.room_b), amount=1),
            "bank account does not exist",
        ),
        (
            RepayLoanHandler(),
            _handler_cmd(scenario, "repay-loan", loan_id="entity_999", amount=0),
            "repayment amount must be positive",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    character.add_relationship(MemberOfInstitution(rank="member", since_epoch=0), institution_id)
    result = UseInstitutionServiceHandler().execute(
        ctx,
        _handler_cmd(scenario, "use-institution-service", service_id=str(service_id)),
    )
    assert result.ok is False
    assert result.reason == "institution rank is too low"

    result = JoinInstitutionHandler().execute(
        ctx,
        _handler_cmd(scenario, "join-institution", institution_id=str(institution_id)),
    )
    assert result.ok is False
    assert result.reason == "already an institution member"

    scenario.actor.world.get_entity(bank_id).add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), account.id
    )
    for handler, command, reason in (
        (
            OpenBankAccountHandler(),
            _handler_cmd(scenario, "open-bank-account", bank_id=str(bank_id)),
            "bank account already exists",
        ),
        (
            WithdrawHandler(),
            _handler_cmd(scenario, "withdraw", bank_id=str(bank_id), amount=1),
            "insufficient bank balance",
        ),
    ):
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_investigate_rumor_ignores_invalid_or_non_site_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    prop = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="old marker", kind="prop")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), prop.id
    )
    invalid_target_rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="invalid target rumor", kind="rumor"),
            RumorComponent(
                text="The map points nowhere.",
                heard_by=(str(scenario.character),),
            ),
            RumorReliabilityComponent(score=1.0),
            RumorTargetComponent(target_id="not-an-entity"),
        ],
    )
    non_site_rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="marker rumor", kind="rumor"),
            RumorComponent(
                text="The marker is important.",
                heard_by=(str(scenario.character),),
            ),
            RumorReliabilityComponent(score=1.0),
            RumorTargetComponent(target_id=str(prop.id)),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), invalid_target_rumor.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), non_site_rumor.id)

    for rumor_id in (invalid_target_rumor.id, non_site_rumor.id):
        result = InvestigateRumorHandler().execute(
            ctx,
            _handler_cmd(scenario, "investigate-rumor", rumor_id=str(rumor_id)),
        )

        assert result.ok is True
        assert [type(event) for event in result.events] == [RumorVerifiedEvent]


def test_use_institution_service_can_succeed_without_output_item():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    institution = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Quiet Guild", kind="institution"),
            InstitutionComponent(name="Quiet Guild", institution_type="guild"),
        ],
    )
    service = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="advice desk", kind="service"),
            InstitutionServiceComponent(service_name="advice", output_item_name=""),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), institution.id
    )
    institution.add_relationship(Contains(mode=ContainmentMode.CONTAINER), service.id)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOfInstitution(rank="member", since_epoch=0), institution.id)

    result = UseInstitutionServiceHandler().execute(
        ctx,
        _handler_cmd(scenario, "use-institution-service", service_id=str(service.id)),
    )

    assert result.ok is True
    event = result.events[0]
    assert isinstance(event, InstitutionServiceUsedEvent)
    assert event.output_item_id is None


def test_daggersim_repay_loan_handler_rejects_bad_entities_and_components():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    bank_id = _bank(scenario)
    account = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bank account", kind="bank-account"),
            BankAccountComponent(bank_id=str(bank_id), owner_id=str(scenario.character)),
        ],
    )
    scenario.actor.world.get_entity(bank_id).add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), account.id
    )
    wrong_kind_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="notice board", kind="prop")],
    ).id
    wrong_borrower_loan = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="borrowed loan", kind="loan"),
            LoanComponent(
                bank_id=str(bank_id),
                borrower_id="entity_999",
                principal=10,
                balance=10,
                due_at_epoch=HOUR,
            ),
        ],
    )
    inactive_loan = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="repaid loan", kind="loan"),
            LoanComponent(
                bank_id=str(bank_id),
                borrower_id=str(scenario.character),
                principal=10,
                balance=0,
                due_at_epoch=HOUR,
                status="repaid",
            ),
        ],
    )
    invalid_bank_loan = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bad bank loan", kind="loan"),
            LoanComponent(
                bank_id="not-an-entity",
                borrower_id=str(scenario.character),
                principal=10,
                balance=10,
                due_at_epoch=HOUR,
            ),
        ],
    )
    accountless_loan = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="accountless loan", kind="loan"),
            LoanComponent(
                bank_id=str(scenario.room_b),
                borrower_id=str(scenario.character),
                principal=10,
                balance=10,
                due_at_epoch=HOUR,
            ),
        ],
    )
    payable_loan = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="payable loan", kind="loan"),
            LoanComponent(
                bank_id=str(bank_id),
                borrower_id=str(scenario.character),
                principal=10,
                balance=10,
                due_at_epoch=HOUR,
            ),
        ],
    )

    for loan_id, reason in (
        ("entity_999", "loan does not exist"),
        (str(wrong_kind_id), "target is not a loan"),
        (str(wrong_borrower_loan.id), "loan is not borrowed by character"),
        (str(inactive_loan.id), "loan is not active"),
        (str(invalid_bank_loan.id), "loan bank is invalid"),
        (str(accountless_loan.id), "bank account does not exist"),
        (str(payable_loan.id), "insufficient bank balance"),
    ):
        result = RepayLoanHandler().execute(
            ctx,
            _handler_cmd(scenario, "repay-loan", loan_id=loan_id, amount=1),
        )
        assert result.ok is False
        assert result.reason == reason


def test_daggersim_crime_magic_and_affliction_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    wrong_kind_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="notice board", kind="prop")],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind_id
    )
    class_template_id = _class_template(scenario)
    spell_template_id = _spell_template(scenario)
    distant_class_template = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far class", kind="class-template"),
            ClassTemplateComponent(
                class_name="Far Class",
                primary_skills=(),
                major_skills=(),
                minor_skills=(),
            ),
        ],
    )
    distant_spell = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant spell", kind="spell"),
            CustomSpellComponent(
                spell_name="Distant Spark",
                effect_type="harm",
                magnitude=1.0,
                creator_id=str(scenario.character),
            ),
        ],
    )
    distant_spell_template = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far spell template", kind="spell-template"),
            SpellTemplateComponent(
                spell_name="Far Spark",
                effect_type="harm",
                magnitude=1.0,
            ),
        ],
    )
    distant_item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far ring", kind="item"), PortableComponent()],
    )
    item_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="iron ring", kind="item"), PortableComponent()],
    ).id
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item_id)
    spell_item_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="spell scroll", kind="item"),
            PortableComponent(),
            CustomSpellComponent(
                spell_name="Scroll Spark",
                effect_type="harm",
                magnitude=1.0,
                creator_id=str(scenario.character),
            ),
        ],
    ).id
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), spell_item_id)
    custom_spell_id = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="mend sprout", kind="spell"),
            CustomSpellComponent(
                spell_name="Mend Sprout",
                effect_type="heal",
                magnitude=4.0,
                creator_id=str(scenario.character),
            ),
        ],
    ).id
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), custom_spell_id)
    hostile_id = _hostile_creature(scenario)
    distant_creature = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far moth", kind="creature"),
            CreatureLanguageComponent(language="Mothwing", pacification_difficulty=1),
        ],
    )
    bank_id = _bank(scenario)
    account = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bank account", kind="bank-account"),
            BankAccountComponent(
                bank_id=str(bank_id),
                owner_id=str(scenario.character),
                balance=0,
            ),
        ],
    )
    scenario.actor.world.get_entity(bank_id).add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), account.id
    )
    open_crime = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="open crime", kind="crime-record"),
            CrimeRecordComponent(crime_type="trespass", region_id="moss-road", fine=5),
        ],
    )
    accountless_crime = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="accountless crime", kind="crime-record"),
            CrimeRecordComponent(crime_type="poaching", region_id="moss-road", fine=5),
        ],
    )
    accountless_character = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Accountless", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), accountless_character.id
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), accountless_crime.id
    )
    distant_crime = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant crime", kind="crime-record"),
            CrimeRecordComponent(crime_type="trespass", region_id="moss-road", fine=5),
        ],
    )
    paid_crime = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="paid crime", kind="crime-record"),
            CrimeRecordComponent(
                crime_type="trespass",
                region_id="moss-road",
                fine=5,
                status="paid",
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), open_crime.id
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), paid_crime.id
    )

    cases = [
        (
            CommitCrimeHandler(),
            _handler_cmd(scenario, "commit-crime", crime_type="trespass"),
            "no law region applies",
        ),
        (
            PayFineHandler(),
            _handler_cmd(scenario, "pay-fine", crime_id="entity_999"),
            "crime record does not exist",
        ),
        (
            PayFineHandler(),
            _handler_cmd(scenario, "pay-fine", crime_id=str(distant_crime.id)),
            "crime record is not reachable",
        ),
        (
            PayFineHandler(),
            _handler_cmd(scenario, "pay-fine", crime_id=str(wrong_kind_id)),
            "target is not a crime record",
        ),
        (
            PayFineHandler(),
            _handler_cmd(scenario, "pay-fine", crime_id=str(paid_crime.id)),
            "crime record is not open",
        ),
        (
            PayFineHandler(),
            _handler_cmd(
                scenario,
                "pay-fine",
                character_id=str(accountless_character.id),
                crime_id=str(accountless_crime.id),
            ),
            "bank account does not exist",
        ),
        (
            PayFineHandler(),
            _handler_cmd(scenario, "pay-fine", crime_id=str(open_crime.id)),
            "insufficient bank balance",
        ),
        (
            CreateCustomClassHandler(),
            _handler_cmd(scenario, "create-custom-class", template_id="entity_999"),
            "class template does not exist",
        ),
        (
            CreateCustomClassHandler(),
            _handler_cmd(
                scenario,
                "create-custom-class",
                template_id=str(distant_class_template.id),
            ),
            "class template is not reachable",
        ),
        (
            CreateCustomClassHandler(),
            _handler_cmd(
                scenario,
                "create-custom-class",
                template_id=str(wrong_kind_id),
            ),
            "target is not a class template",
        ),
        (
            CreateSpellHandler(),
            _handler_cmd(scenario, "create-spell", template_id="entity_999"),
            "spell template does not exist",
        ),
        (
            CreateSpellHandler(),
            _handler_cmd(
                scenario,
                "create-spell",
                template_id=str(distant_spell_template.id),
            ),
            "spell template is not reachable",
        ),
        (
            CreateSpellHandler(),
            _handler_cmd(scenario, "create-spell", template_id=str(wrong_kind_id)),
            "target is not a spell template",
        ),
        (
            CastSpellHandler(),
            _handler_cmd(scenario, "cast-spell", spell_id="entity_999"),
            "spell or target does not exist",
        ),
        (
            CastSpellHandler(),
            _handler_cmd(scenario, "cast-spell", spell_id=str(distant_spell.id)),
            "spell is not reachable",
        ),
        (
            CastSpellHandler(),
            _handler_cmd(scenario, "cast-spell", spell_id=str(wrong_kind_id)),
            "target is not a spell or enchanted item",
        ),
        (
            EnchantItemHandler(),
            _handler_cmd(
                scenario,
                "enchant-item",
                item_id=str(distant_item.id),
                spell_id=str(custom_spell_id),
            ),
            "item is not reachable",
        ),
        (
            EnchantItemHandler(),
            _handler_cmd(
                scenario,
                "enchant-item",
                item_id=str(item_id),
                spell_id=str(distant_spell.id),
            ),
            "spell is not reachable",
        ),
        (
            EnchantItemHandler(),
            _handler_cmd(
                scenario,
                "enchant-item",
                item_id=str(item_id),
                spell_id="entity_999",
            ),
            "item or spell does not exist",
        ),
        (
            EnchantItemHandler(),
            _handler_cmd(
                scenario,
                "enchant-item",
                item_id=str(wrong_kind_id),
                spell_id=str(custom_spell_id),
            ),
            "target is not an item",
        ),
        (
            EnchantItemHandler(),
            _handler_cmd(
                scenario,
                "enchant-item",
                item_id=str(spell_template_id),
                spell_id=str(custom_spell_id),
            ),
            "target is not an item",
        ),
        (
            EnchantItemHandler(),
            _handler_cmd(
                scenario,
                "enchant-item",
                item_id=str(spell_item_id),
                spell_id=str(custom_spell_id),
            ),
            "target item is a spell",
        ),
        (
            EnchantItemHandler(),
            _handler_cmd(
                scenario,
                "enchant-item",
                item_id=str(item_id),
                spell_id=str(wrong_kind_id),
            ),
            "source is not a spell",
        ),
        (
            AttemptPacifyHandler(),
            _handler_cmd(scenario, "attempt-pacify", target_id="entity_999"),
            "target does not exist",
        ),
        (
            AttemptPacifyHandler(),
            _handler_cmd(
                scenario,
                "attempt-pacify",
                target_id=str(distant_creature.id),
            ),
            "target is not reachable",
        ),
        (
            AttemptPacifyHandler(),
            _handler_cmd(scenario, "attempt-pacify", target_id=str(wrong_kind_id)),
            "target has no creature language",
        ),
        (
            AttemptPacifyHandler(),
            _handler_cmd(scenario, "attempt-pacify", target_id=str(hostile_id)),
            "character knows no creature languages",
        ),
        (
            ContractAfflictionHandler(),
            _handler_cmd(scenario, "contract-affliction", affliction_type=" "),
            "invalid character or affliction type",
        ),
        (
            TransformHandler(),
            _handler_cmd(scenario, "transform"),
            "character has no supernatural affliction",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    _law_region(scenario)
    replace_component(
        scenario.actor.world.get_entity(scenario.room_a),
        LawRegionComponent(region_id="moss-road", fines={"trespass": 15}),
    )
    result = CommitCrimeHandler().execute(
        ctx,
        _handler_cmd(scenario, "commit-crime", crime_type="unknown"),
    )
    assert result.ok is False
    assert result.reason == "crime is not fineable"

    character.add_component(CustomClassComponent(class_name="Moonlit Forager"))
    result = CreateCustomClassHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "create-custom-class",
            template_id=str(class_template_id),
        ),
    )
    assert result.ok is False
    assert result.reason == "character already has a custom class"

    character.add_component(
        SupernaturalAfflictionComponent(
            affliction_type="werehare",
            contracted_at_epoch=scenario.actor.epoch,
        )
    )
    result = ContractAfflictionHandler().execute(
        ctx,
        _handler_cmd(scenario, "contract-affliction", affliction_type="vampire"),
    )
    assert result.ok is False
    assert result.reason == "character already has a supernatural affliction"

    character.add_component(
        WereformComponent(form_name="werehare", transformed_at_epoch=scenario.actor.epoch)
    )
    result = TransformHandler().execute(ctx, _handler_cmd(scenario, "transform"))
    assert result.ok is False
    assert result.reason == "character is already transformed"


def test_pay_fine_succeeds_when_crime_has_no_bounty_component():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    bank_id = _bank(scenario)
    account = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bank account", kind="bank-account"),
            BankAccountComponent(
                bank_id=str(bank_id),
                owner_id=str(scenario.character),
                balance=25,
            ),
        ],
    )
    scenario.actor.world.get_entity(bank_id).add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), account.id
    )
    crime = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="minor trespass", kind="crime-record"),
            CrimeRecordComponent(crime_type="trespass", region_id="moss-road", fine=10),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), crime.id
    )

    result = PayFineHandler().execute(
        ctx,
        _handler_cmd(scenario, "pay-fine", crime_id=str(crime.id)),
    )

    assert result.ok is True
    assert isinstance(result.events[0], FinePaidEvent)
    assert account.get_component(BankAccountComponent).balance == 15
    assert crime.get_component(CrimeRecordComponent).status == "paid"


def test_buy_property_handler_rejects_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="notice board", kind="prop")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id
    )
    distant_property = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Far Cottage", kind="property"),
            PropertyDeedComponent(price=1),
        ],
    )
    owned_property = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Owned Cottage", kind="property"),
            PropertyDeedComponent(price=1, owner_id="entity_999"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), owned_property.id
    )
    property_id = _property(scenario, price=5)

    handler = BuyPropertyHandler()
    cases = [
        (
            _handler_cmd(scenario, "buy-property", property_id="entity_999"),
            "property does not exist",
        ),
        (
            _handler_cmd(scenario, "buy-property", property_id=str(distant_property.id)),
            "property is not reachable",
        ),
        (
            _handler_cmd(scenario, "buy-property", property_id=str(wrong_kind.id)),
            "target is not purchasable property",
        ),
        (
            _handler_cmd(scenario, "buy-property", property_id=str(owned_property.id)),
            "property already has an owner",
        ),
        (
            _handler_cmd(scenario, "buy-property", property_id=str(property_id)),
            "bank account does not exist",
        ),
    ]
    for command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    bank_id = _bank(scenario)
    account = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="bank account", kind="bank-account"),
            BankAccountComponent(bank_id=str(bank_id), owner_id=str(scenario.character)),
        ],
    )
    scenario.actor.world.get_entity(bank_id).add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), account.id
    )
    result = handler.execute(
        ctx,
        _handler_cmd(scenario, "buy-property", property_id=str(property_id)),
    )
    assert result.ok is False
    assert result.reason == "insufficient bank balance"


def test_enchant_item_can_use_spell_template_as_source():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    spell_id = _spell_template(scenario)
    charm = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="plain charm", kind="item"),
            PortableComponent(),
        ],
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), charm.id)

    result = EnchantItemHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "enchant-item",
            item_id=str(charm.id),
            spell_id=str(spell_id),
        ),
    )

    assert result.ok is True
    assert isinstance(result.events[0], ItemEnchantedEvent)
    enchantment = charm.get_component(EnchantedItemComponent)
    assert enchantment.spell_name == "Mend Sprout"
    assert enchantment.source_spell_id == str(spell_id)


def test_daggersim_handlers_reject_invalid_character_ids_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cases = [
        (
            ExpandSiteHandler(),
            "expand-site",
            {"site_id": str(scenario.room_a)},
            "invalid character or site id",
        ),
        (
            AskRumorHandler(),
            "ask-rumor",
            {"rumor_id": str(scenario.room_a)},
            "invalid character id",
        ),
        (
            PlanTravelHandler(),
            "plan-travel",
            {"destination_id": str(scenario.room_a)},
            "invalid character or destination id",
        ),
        (
            JoinInstitutionHandler(),
            "join-institution",
            {"institution_id": str(scenario.room_a)},
            "invalid character or institution id",
        ),
        (
            UseInstitutionServiceHandler(),
            "use-institution-service",
            {"service_id": str(scenario.room_a)},
            "invalid character or service id",
        ),
        (
            AskForWorkHandler(),
            "ask-for-work",
            {"template_id": str(scenario.room_a)},
            "invalid character or template id",
        ),
        (
            AcceptGeneratedQuestHandler(),
            "accept-generated-quest",
            {"quest_id": str(scenario.room_a)},
            "invalid character or quest id",
        ),
        (
            CompleteGeneratedQuestHandler(),
            "complete-generated-quest",
            {"quest_id": str(scenario.room_a)},
            "invalid character or quest id",
        ),
        (
            OpenBankAccountHandler(),
            "open-bank-account",
            {"bank_id": str(scenario.room_a)},
            "invalid character or bank id",
        ),
        (
            DepositHandler(),
            "deposit",
            {"bank_id": str(scenario.room_a), "amount": 1},
            "invalid character or bank id",
        ),
        (
            WithdrawHandler(),
            "withdraw",
            {"bank_id": str(scenario.room_a), "amount": 1},
            "invalid character or bank id",
        ),
        (
            TakeLoanHandler(),
            "take-loan",
            {"bank_id": str(scenario.room_a), "amount": 1},
            "invalid character or bank id",
        ),
        (
            RepayLoanHandler(),
            "repay-loan",
            {"loan_id": str(scenario.room_a), "amount": 1},
            "invalid character or loan id",
        ),
        (
            CommitCrimeHandler(),
            "commit-crime",
            {"crime_type": "trespass"},
            "invalid character or crime type",
        ),
        (
            PayFineHandler(),
            "pay-fine",
            {"crime_id": str(scenario.room_a)},
            "invalid character or crime id",
        ),
        (
            BuyPropertyHandler(),
            "buy-property",
            {"property_id": str(scenario.room_a)},
            "invalid character or property id",
        ),
        (
            CreateCustomClassHandler(),
            "create-custom-class",
            {"template_id": str(scenario.room_a), "name": "Scout"},
            "invalid character or class template id",
        ),
        (
            CreateSpellHandler(),
            "create-spell",
            {"template_id": str(scenario.room_a), "name": "Spark"},
            "invalid character or spell template id",
        ),
        (
            CastSpellHandler(),
            "cast-spell",
            {"spell_id": str(scenario.room_a), "target_id": str(scenario.character)},
            "invalid character, spell, or target id",
        ),
        (
            EnchantItemHandler(),
            "enchant-item",
            {"item_id": str(scenario.room_a), "spell_id": str(scenario.character)},
            "invalid character, item, or spell id",
        ),
        (
            AttemptPacifyHandler(),
            "attempt-pacify",
            {"target_id": str(scenario.character)},
            "invalid character or target id",
        ),
        (
            ContractAfflictionHandler(),
            "contract-affliction",
            {"affliction_type": "moon-form"},
            "invalid character or affliction type",
        ),
        (TransformHandler(), "transform", {"form_name": "moon hare"}, "invalid character id"),
        (
            RequestDungeonHandler(),
            "request-dungeon",
            {"dungeon_id": str(scenario.room_a)},
            "invalid character or dungeon id",
        ),
        (
            EnterDungeonHandler(),
            "enter-dungeon",
            {"dungeon_id": str(scenario.room_a)},
            "invalid character or dungeon id",
        ),
        (SearchRoomHandler(), "search-room", {}, "invalid character id"),
        (
            OpenSecretDoorHandler(),
            "open-secret-door",
            {"door_id": str(scenario.room_a)},
            "invalid character or door id",
        ),
        (MarkPathHandler(), "mark-path", {}, "invalid character id"),
        (ViewMapHandler(), "view-map", {}, "invalid character id"),
        (SetRecallHandler(), "set-recall", {}, "invalid character id"),
        (UseRecallHandler(), "use-recall", {}, "invalid character id"),
        (RestHandler(), "rest", {}, "invalid character id"),
        (
            LeaveDungeonHandler(),
            "leave-dungeon",
            {"dungeon_id": str(scenario.room_a)},
            "invalid character or dungeon id",
        ),
    ]

    for handler, command_type, payload, reason in cases:
        result = handler.execute(
            ctx,
            _handler_cmd(
                scenario,
                command_type,
                character_id="not-an-id",
                **payload,
            ),
        )
        assert result.ok is False
        assert result.reason == reason

    missing = CommitCrimeHandler().execute(
        ctx,
        _handler_cmd(
            scenario,
            "commit-crime",
            character_id="entity_999999",
            crime_type="trespass",
        ),
    )
    assert missing.ok is False
    assert missing.reason == "character does not exist"


async def test_plan_travel_moves_character_after_route_time():
    scenario = build_scenario()
    _install(scenario.actor)
    _travel_route(scenario)
    started: list[TravelStartedEvent] = []
    completed: list[TravelCompletedEvent] = []
    scenario.actor.bus.subscribe(TravelStartedEvent, started.append)
    scenario.actor.bus.subscribe(TravelCompletedEvent, completed.append)

    await scenario.actor.submit(
        _cmd(scenario, "plan-travel", destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert scenario.character_room() == scenario.room_a
    assert character.has_component(TravelPlanComponent)
    assert started[0].destination_id == str(scenario.room_b)

    await scenario.actor.tick(HOUR)
    assert scenario.character_room() == scenario.room_a

    await scenario.actor.tick(HOUR)
    assert scenario.character_room() == scenario.room_b
    assert not character.has_component(TravelPlanComponent)
    assert completed[0].destination_id == str(scenario.room_b)


async def test_travel_mode_speed_shortens_route_time():
    scenario = build_scenario()
    _install(scenario.actor)
    _travel_route(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(TravelModeComponent(mode="cart", speed_multiplier=2.0))

    await scenario.actor.submit(
        _cmd(scenario, "plan-travel", destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_a
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_b
    assert not character.has_component(TravelPlanComponent)


async def test_join_institution_and_use_member_service_grants_output_item():
    scenario = build_scenario()
    _install(scenario.actor)
    institution_id, service_id = _institution(scenario)
    joined: list[InstitutionJoinedEvent] = []
    used: list[InstitutionServiceUsedEvent] = []
    reputation: list[InstitutionReputationChangedEvent] = []
    access: list[ServiceAccessChangedEvent] = []
    scenario.actor.bus.subscribe(InstitutionJoinedEvent, joined.append)
    scenario.actor.bus.subscribe(InstitutionServiceUsedEvent, used.append)
    scenario.actor.bus.subscribe(InstitutionReputationChangedEvent, reputation.append)
    scenario.actor.bus.subscribe(ServiceAccessChangedEvent, access.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-institution", institution_id=str(institution_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "use-institution-service", service_id=str(service_id))
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(MemberOfInstitution, institution_id)
    assert character.get_component(InstitutionReputationComponent).scores[
        str(institution_id)
    ] == 2
    assert character.get_component(ServiceAccessComponent).service_ids == (str(service_id),)
    assert joined[0].institution_name == "Burrow Cartographers"
    assert [event.score for event in reputation] == [1, 2]
    assert access[0].service_id == str(service_id)
    output_id = parse_entity_id(used[0].output_item_id)
    assert output_id is not None
    output = scenario.actor.world.get_entity(output_id)
    assert output.get_component(IdentityComponent).name == "moss road map"
    assert container_of(output) == scenario.character


async def test_institution_service_rejects_insufficient_rank():
    scenario = build_scenario()
    _install(scenario.actor)
    institution_id, service_id = _institution(scenario, required_rank="officer")
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-institution", institution_id=str(institution_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "use-institution-service", service_id=str(service_id))
    )
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "institution rank is too low" for event in rejects)


async def test_institution_service_can_require_deed_reputation():
    scenario = build_scenario()
    _install(scenario.actor)
    institution_id, service_id = _institution(
        scenario, required_deed_tag="crafted", required_deed_score=1.0
    )
    rejects: list[CommandRejectedEvent] = []
    used: list[InstitutionServiceUsedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    scenario.actor.bus.subscribe(InstitutionServiceUsedEvent, used.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-institution", institution_id=str(institution_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "use-institution-service", service_id=str(service_id))
    )
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "required deed reputation is too low" for event in rejects)

    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        DeedReputationComponent(
            scores={"crafted": 1.25},
            deed_ids=("history_1",),
            known_for=("crafted a camp kit",),
        )
    )
    await scenario.actor.submit(
        _cmd(scenario, "use-institution-service", service_id=str(service_id))
    )
    await scenario.actor.tick(HOUR)

    assert used[0].service_id == str(service_id)


async def test_generated_quest_can_be_accepted_completed_and_rewarded():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _quest_template(scenario)
    generated: list[QuestGeneratedEvent] = []
    accepted: list[QuestAcceptedEvent] = []
    completed: list[QuestCompletedEvent] = []
    scenario.actor.bus.subscribe(QuestGeneratedEvent, generated.append)
    scenario.actor.bus.subscribe(QuestAcceptedEvent, accepted.append)
    scenario.actor.bus.subscribe(QuestCompletedEvent, completed.append)

    await scenario.actor.submit(_cmd(scenario, "ask-for-work", template_id=str(template_id)))
    await scenario.actor.tick(HOUR)
    quest_id = parse_entity_id(generated[0].quest_id)
    assert quest_id is not None

    await scenario.actor.submit(
        _cmd(scenario, "accept-generated-quest", quest_id=str(quest_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "complete-generated-quest", quest_id=str(quest_id))
    )
    await scenario.actor.tick(HOUR)

    quest = scenario.actor.world.get_entity(quest_id)
    assert quest.get_component(GeneratedQuestComponent).status == "completed"
    assert quest.get_component(DaggerQuestRewardComponent).claimed is True
    assert accepted[0].quest_id == str(quest_id)
    reward_id = parse_entity_id(completed[0].reward_item_id)
    assert reward_id is not None
    reward = scenario.actor.world.get_entity(reward_id)
    assert reward.get_component(IdentityComponent).name == "guild writ"
    assert container_of(reward) == scenario.character


async def test_generated_quest_fails_after_deadline():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _quest_template(scenario, duration_seconds=HOUR)
    generated: list[QuestGeneratedEvent] = []
    failed: list[QuestFailedEvent] = []
    scenario.actor.bus.subscribe(QuestGeneratedEvent, generated.append)
    scenario.actor.bus.subscribe(QuestFailedEvent, failed.append)

    await scenario.actor.submit(_cmd(scenario, "ask-for-work", template_id=str(template_id)))
    await scenario.actor.tick(HOUR)
    quest_id = parse_entity_id(generated[0].quest_id)
    assert quest_id is not None

    await scenario.actor.submit(
        _cmd(scenario, "accept-generated-quest", quest_id=str(quest_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(1)

    quest = scenario.actor.world.get_entity(quest_id)
    assert quest.get_component(GeneratedQuestComponent).status == "failed"
    assert quest.get_component(QuestDeadlineComponent).due_at_epoch < scenario.actor.epoch
    assert failed[0].quest_id == str(quest_id)


async def test_bank_account_loan_and_repayment_update_balances():
    scenario = build_scenario()
    _install(scenario.actor)
    bank_id = _bank(scenario)
    opened: list[AccountOpenedEvent] = []
    issued: list[LoanIssuedEvent] = []
    repaid: list[LoanRepaidEvent] = []
    scenario.actor.bus.subscribe(AccountOpenedEvent, opened.append)
    scenario.actor.bus.subscribe(LoanIssuedEvent, issued.append)
    scenario.actor.bus.subscribe(LoanRepaidEvent, repaid.append)

    await scenario.actor.submit(_cmd(scenario, "open-bank-account", bank_id=str(bank_id)))
    await scenario.actor.tick(HOUR)
    account_id = parse_entity_id(opened[0].account_id)
    assert account_id is not None

    await scenario.actor.submit(
        _cmd(scenario, "take-loan", bank_id=str(bank_id), amount=25)
    )
    await scenario.actor.tick(HOUR)
    loan_id = parse_entity_id(issued[0].loan_id)
    assert loan_id is not None

    account = scenario.actor.world.get_entity(account_id)
    loan = scenario.actor.world.get_entity(loan_id)
    assert account.get_component(BankAccountComponent).balance == 25
    assert loan.get_component(LoanComponent).balance == 25

    await scenario.actor.submit(_cmd(scenario, "repay-loan", loan_id=str(loan_id), amount=10))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "repay-loan", loan_id=str(loan_id), amount=15))
    await scenario.actor.tick(HOUR)

    assert account.get_component(BankAccountComponent).balance == 0
    assert loan.get_component(LoanComponent).balance == 0
    assert loan.get_component(LoanComponent).status == "repaid"
    assert repaid[-1].balance == 0


async def test_unpaid_loan_defaults_into_debt():
    scenario = build_scenario()
    _install(scenario.actor)
    bank_id = _bank(scenario)
    issued: list[LoanIssuedEvent] = []
    defaulted: list[LoanDefaultedEvent] = []
    scenario.actor.bus.subscribe(LoanIssuedEvent, issued.append)
    scenario.actor.bus.subscribe(LoanDefaultedEvent, defaulted.append)

    await scenario.actor.submit(_cmd(scenario, "open-bank-account", bank_id=str(bank_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "take-loan", bank_id=str(bank_id), amount=30, duration_seconds=HOUR)
    )
    await scenario.actor.tick(HOUR)
    loan_id = parse_entity_id(issued[0].loan_id)
    assert loan_id is not None

    await scenario.actor.tick(HOUR + 1)

    loan = scenario.actor.world.get_entity(loan_id)
    assert loan.get_component(LoanComponent).status == "defaulted"
    assert loan.get_component(DebtComponent).amount == 30
    assert defaulted[0].loan_id == str(loan_id)


async def test_crime_posts_bounty_and_pay_fine_resolves_record_from_bank_account():
    scenario = build_scenario()
    _install(scenario.actor)
    _law_region(scenario)
    bank_id = _bank(scenario)
    opened: list[AccountOpenedEvent] = []
    crimes: list[CrimeCommittedEvent] = []
    bounties: list[BountyPostedEvent] = []
    paid: list[FinePaidEvent] = []
    legal: list[LegalReputationChangedEvent] = []
    scenario.actor.bus.subscribe(AccountOpenedEvent, opened.append)
    scenario.actor.bus.subscribe(CrimeCommittedEvent, crimes.append)
    scenario.actor.bus.subscribe(BountyPostedEvent, bounties.append)
    scenario.actor.bus.subscribe(FinePaidEvent, paid.append)
    scenario.actor.bus.subscribe(LegalReputationChangedEvent, legal.append)

    await scenario.actor.submit(_cmd(scenario, "open-bank-account", bank_id=str(bank_id)))
    await scenario.actor.tick(HOUR)
    account_id = parse_entity_id(opened[0].account_id)
    assert account_id is not None
    await scenario.actor.submit(_cmd(scenario, "deposit", bank_id=str(bank_id), amount=20))
    await scenario.actor.tick(HOUR)

    await scenario.actor.submit(_cmd(scenario, "commit-crime", crime_type="trespass"))
    await scenario.actor.tick(HOUR)
    crime_id = parse_entity_id(crimes[0].crime_id)
    assert crime_id is not None
    crime = scenario.actor.world.get_entity(crime_id)
    assert crime.get_component(CrimeRecordComponent).fine == 15
    assert crime.get_component(BountyComponent).amount == 15
    assert bounties[0].amount == 15
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(LegalReputationComponent).scores["moss-road"] == -15

    await scenario.actor.submit(_cmd(scenario, "pay-fine", crime_id=str(crime_id)))
    await scenario.actor.tick(HOUR)

    account = scenario.actor.world.get_entity(account_id)
    assert account.get_component(BankAccountComponent).balance == 5
    assert crime.get_component(CrimeRecordComponent).status == "paid"
    assert not crime.has_component(BountyComponent)
    assert paid[0].crime_id == str(crime_id)
    assert character.get_component(LegalReputationComponent).scores["moss-road"] == 0
    assert [event.score for event in legal] == [-15, 0]


async def test_buy_property_spends_bank_balance_and_records_deed_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    bank_id = _bank(scenario)
    property_id = _property(scenario, price=12)
    opened: list[AccountOpenedEvent] = []
    purchased: list[PropertyPurchasedEvent] = []
    scenario.actor.bus.subscribe(AccountOpenedEvent, opened.append)
    scenario.actor.bus.subscribe(PropertyPurchasedEvent, purchased.append)

    await scenario.actor.submit(_cmd(scenario, "open-bank-account", bank_id=str(bank_id)))
    await scenario.actor.tick(HOUR)
    account_id = parse_entity_id(opened[0].account_id)
    assert account_id is not None
    await scenario.actor.submit(_cmd(scenario, "deposit", bank_id=str(bank_id), amount=20))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "buy-property", property_id=str(property_id)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    property_entity = scenario.actor.world.get_entity(property_id)
    account = scenario.actor.world.get_entity(account_id)
    assert character.has_relationship(OwnsProperty, property_id)
    assert property_entity.get_component(PropertyDeedComponent).owner_id == str(
        scenario.character
    )
    assert account.get_component(BankAccountComponent).balance == 8
    assert purchased[0].price == 12
    assert "Property owned: Moss Road Cottage." in daggersim_fragments(
        scenario.actor.world, character
    )


async def test_create_custom_class_from_template_sets_character_build():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _class_template(scenario)
    created: list[CustomClassCreatedEvent] = []
    scenario.actor.bus.subscribe(CustomClassCreatedEvent, created.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "create-custom-class",
            template_id=str(template_id),
            class_name="Rainpath Scout",
            primary_skills=("foraging", "stealth", "weather lore"),
        )
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    custom_class = character.get_component(CustomClassComponent)
    assert custom_class.class_name == "Rainpath Scout"
    assert custom_class.primary_skills == ("foraging", "stealth", "weather lore")
    assert custom_class.major_skills == ("cooking", "animal speech", "memory")
    assert custom_class.advantages == ("night vision",)
    assert created[0].class_name == "Rainpath Scout"


async def test_create_and_cast_custom_spell_heals_target_health():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _spell_template(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=3.0, maximum=10.0))
    created: list[SpellCreatedEvent] = []
    cast: list[SpellCastEvent] = []
    scenario.actor.bus.subscribe(SpellCreatedEvent, created.append)
    scenario.actor.bus.subscribe(SpellCastEvent, cast.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "create-spell",
            template_id=str(template_id),
            spell_name="Mend Moss",
        )
    )
    await scenario.actor.tick(HOUR)
    spell_id = parse_entity_id(created[0].spell_id)
    assert spell_id is not None

    await scenario.actor.submit(
        _cmd(
            scenario,
            "cast-spell",
            spell_id=str(spell_id),
            target_id=str(scenario.character),
        )
    )
    await scenario.actor.tick(HOUR)

    spell = scenario.actor.world.get_entity(spell_id)
    assert spell.get_component(CustomSpellComponent).spell_name == "Mend Moss"
    assert container_of(spell) == scenario.character
    assert character.get_component(HealthComponent).current == 7.0
    assert cast[0].target_health == 7.0


def test_apply_spell_effect_handles_health_branches():
    scenario = build_scenario()
    target = scenario.actor.world.get_entity(scenario.character)
    no_health = spawn_entity(scenario.actor.world, [IdentityComponent(name="rock", kind="item")])

    assert (
        _apply_spell_effect(
            no_health,
            CustomSpellComponent(spell_name="Mend", effect_type="heal", magnitude=4.0),
        )
        is None
    )

    target.add_component(HealthComponent(current=8.0, maximum=10.0))
    assert (
        _apply_spell_effect(
            target,
            CustomSpellComponent(spell_name="Mend", effect_type="heal", magnitude=4.0),
        )
        == 10.0
    )
    assert (
        _apply_spell_effect(
            target,
            EnchantedItemComponent(spell_name="Bolt", effect_type="harm", magnitude=12.0),
        )
        == 0.0
    )
    assert (
        _apply_spell_effect(
            target,
            CustomSpellComponent(spell_name="Glow", effect_type="light", magnitude=1.0),
        )
        == 0.0
    )


async def test_enchant_item_with_created_spell_and_cast_from_item():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _spell_template(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(HealthComponent(current=1.0, maximum=10.0))
    charm = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="moss charm", kind="item"),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), charm.id)
    created: list[SpellCreatedEvent] = []
    enchanted: list[ItemEnchantedEvent] = []
    cast: list[SpellCastEvent] = []
    scenario.actor.bus.subscribe(SpellCreatedEvent, created.append)
    scenario.actor.bus.subscribe(ItemEnchantedEvent, enchanted.append)
    scenario.actor.bus.subscribe(SpellCastEvent, cast.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "create-spell",
            template_id=str(template_id),
            spell_name="Mend Moss",
        )
    )
    await scenario.actor.tick(HOUR)
    spell_id = parse_entity_id(created[0].spell_id)
    assert spell_id is not None

    await scenario.actor.submit(
        _cmd(
            scenario,
            "enchant-item",
            item_id=str(charm.id),
            spell_id=str(spell_id),
        )
    )
    await scenario.actor.tick(HOUR)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "cast-spell",
            spell_id=str(charm.id),
            target_id=str(scenario.character),
        )
    )
    await scenario.actor.tick(HOUR)

    enchantment = charm.get_component(EnchantedItemComponent)
    assert enchantment.spell_name == "Mend Moss"
    assert enchantment.source_spell_id == str(spell_id)
    assert enchanted[0].item_id == str(charm.id)
    assert enchanted[0].spell_id == str(spell_id)
    assert character.get_component(HealthComponent).current == 5.0
    assert cast[0].spell_id == str(charm.id)
    assert cast[0].spell_name == "Mend Moss"
    assert cast[0].target_health == 5.0


async def test_enchant_item_rejects_non_item_targets():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _spell_template(scenario)
    rejected_events: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejected_events.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "enchant-item",
            item_id=str(scenario.room_a),
            spell_id=str(template_id),
        )
    )
    await scenario.actor.tick(HOUR)

    assert rejected_events[0].reason == "target is not an item"


async def test_language_skill_pacifies_hostile_creature():
    scenario = build_scenario()
    _install(scenario.actor)
    creature_id = _hostile_creature(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(LanguageSkillComponent(languages={"Mothwing": 2}))
    attempts: list[PacificationAttemptedEvent] = []
    pacified: list[CreaturePacifiedEvent] = []
    scenario.actor.bus.subscribe(PacificationAttemptedEvent, attempts.append)
    scenario.actor.bus.subscribe(CreaturePacifiedEvent, pacified.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "attempt-pacify",
            target_id=str(creature_id),
            language="Mothwing",
        )
    )
    await scenario.actor.tick(HOUR)

    creature = scenario.actor.world.get_entity(creature_id)
    assert creature.get_component(HostilityComponent).hostile is False
    assert creature.get_component(PacifiedComponent).pacified_by == str(scenario.character)
    assert attempts[0].succeeded is True
    assert pacified[0].target_id == str(creature_id)


async def test_supernatural_affliction_transforms_and_grows_feeding_need():
    scenario = build_scenario()
    _install(scenario.actor)
    contracted: list[AfflictionContractedEvent] = []
    transformed: list[TransformationStartedEvent] = []
    feeding: list[FeedingNeedChangedEvent] = []
    scenario.actor.bus.subscribe(AfflictionContractedEvent, contracted.append)
    scenario.actor.bus.subscribe(TransformationStartedEvent, transformed.append)
    scenario.actor.bus.subscribe(FeedingNeedChangedEvent, feeding.append)

    await scenario.actor.submit(
        _cmd(scenario, "contract-affliction", affliction_type="moon-form")
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "transform", form_name="moon hare"))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(SupernaturalAfflictionComponent).stage == "active"
    assert character.get_component(WereformComponent).form_name == "moon hare"
    assert character.get_component(FeedingNeedComponent).current > 0
    assert contracted[0].affliction_type == "moon-form"
    assert transformed[0].form_name == "moon hare"
    assert feeding[-1].current > 0


def test_daggersim_fragments_show_nearby_unrealized_locations():
    scenario = build_scenario()
    _site(scenario)

    fragments = daggersim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("Nearby unrealized hamlet: Rain Garden Hamlet" in line for line in fragments)


def test_daggersim_fragments_show_heard_rumors():
    scenario = build_scenario()
    site_id = _site(scenario)
    rumor_id = _rumor(scenario, site_id)
    rumor_entity = scenario.actor.world.get_entity(rumor_id)
    rumor = rumor_entity.get_component(RumorComponent)
    replace_component(
        rumor_entity,
        RumorComponent(text=rumor.text, heard_by=(str(scenario.character),)),
    )

    fragments = daggersim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("Rumor: The old carrot vault" in line for line in fragments)


def test_daggersim_fragments_show_travel_plan():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        TravelPlanComponent(
            destination_id=str(scenario.room_b),
            started_at_epoch=0,
            arrive_at_epoch=HOUR,
        )
    )

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert any("Traveling by foot" in line for line in fragments)


def test_daggersim_component_prompt_fragments_use_target_and_self_context():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    rumor = spawn_entity(
        world,
        [RumorComponent(text="The old carrot vault is open.", heard_by=(str(character.id),))],
    )
    institution = spawn_entity(
        world,
        [
            InstitutionComponent(name="Burrow Cartographers"),
            InstitutionDuesComponent(amount_due=12, paid_by=(str(character.id),)),
        ],
    )
    self_ctx = ComponentPromptContext.for_entity(world, character)
    viewer = spawn_entity(world, [CharacterComponent()])
    rumor_ctx = ComponentPromptContext.for_entity(
        world, rumor, perspective=self_ctx.perspective, target=character
    )
    observer_rumor_ctx = ComponentPromptContext.for_entity(
        world,
        rumor,
        perspective=PromptPerspective(viewer=viewer),
        target=character,
    )
    institution_ctx = ComponentPromptContext.for_entity(
        world, institution, perspective=self_ctx.perspective, target=character
    )
    observer_institution_ctx = ComponentPromptContext.for_entity(
        world,
        institution,
        perspective=PromptPerspective(viewer=viewer),
        target=character,
    )

    assert rumor.get_component(RumorComponent).prompt_fragments(rumor_ctx) == (
        "Rumor: The old carrot vault is open. (unverified).",
    )
    assert rumor.get_component(RumorComponent).prompt_fragments(observer_rumor_ctx) == ()
    assert institution.get_component(InstitutionDuesComponent).prompt_fragments(
        institution_ctx
    ) == ("Institution dues: 12 (paid).",)
    assert institution.get_component(InstitutionDuesComponent).prompt_fragments(
        observer_institution_ctx
    ) == ()
    assert LoanComponent(
        bank_id=str(institution.id),
        borrower_id=str(character.id),
        principal=20,
        balance=15,
        due_at_epoch=9,
    ).prompt_fragments(institution_ctx) == ("Loan: 15 due at epoch 9 (active).",)
    assert LoanComponent(
        bank_id=str(institution.id),
        borrower_id=str(character.id),
        principal=20,
        balance=15,
        due_at_epoch=9,
    ).prompt_fragments(observer_institution_ctx) == ()
    custom_spell = CustomSpellComponent(spell_name="Moon Mend", effect_type="heal", magnitude=3)
    assert custom_spell.prompt_fragments(institution_ctx) == (
        "Known custom spell: Moon Mend (heal).",
    )
    assert custom_spell.prompt_fragments(observer_institution_ctx) == ()
    assert GeneratedQuestComponent(
        title="Accepted",
        objective="help",
        status="accepted",
        accepted_by=str(character.id),
    ).prompt_fragments(institution_ctx) == ("Generated quest: Accepted (accepted).",)
    assert GeneratedQuestComponent(
        title="Accepted",
        objective="help",
        status="accepted",
        accepted_by=str(character.id),
    ).prompt_fragments(observer_institution_ctx) == ()
    assert LetterOfCreditComponent(
        bank_id=str(institution.id),
        owner_id=str(character.id),
        amount=30,
    ).prompt_fragments(institution_ctx) == ("Letter of credit: 30 (active).",)
    assert LetterOfCreditComponent(
        bank_id=str(institution.id),
        owner_id=str(character.id),
        amount=30,
    ).prompt_fragments(observer_institution_ctx) == ()
    assert SafeStorageComponent(owner_id=str(character.id), item_ids=("a", "b")).prompt_fragments(
        institution_ctx
    ) == ("Safe storage: 2 item(s).",)
    assert SafeStorageComponent(owner_id=str(character.id), item_ids=("a", "b")).prompt_fragments(
        observer_institution_ctx
    ) == ()
    assert DebtCollectorComponent(
        borrower_id=str(character.id),
        debt_id="debt",
        pressure=2,
    ).prompt_fragments(institution_ctx) == ("Debt collector pressure: 2.",)
    assert DebtCollectorComponent(
        borrower_id=str(character.id),
        debt_id="debt",
        pressure=2,
    ).prompt_fragments(observer_institution_ctx) == ()
    property_target = spawn_entity(world, [IdentityComponent(name="Burrow Loft", kind="home")])
    assert OwnsProperty(deed_id="deed").prompt_fragments(
        ComponentPromptContext.for_entity(
            world,
            character,
            perspective=self_ctx.perspective,
            target=property_target,
        )
    ) == ("Property owned: Burrow Loft.",)
    assert OwnsProperty(deed_id="deed").prompt_fragments(
        ComponentPromptContext.for_entity(
            world,
            character,
            perspective=PromptPerspective(viewer=viewer),
            target=property_target,
        )
    ) == ()
    assert AutomapComponent(discovered_rooms=("room_a", "room_b")).prompt_fragments(
        self_ctx
    ) == ("Automap: 2 room(s) discovered.",)
    assert CustomClassComponent(class_name="Night Gardener").prompt_fragments(self_ctx) == (
        "Custom class: Night Gardener.",
    )


def test_daggersim_fragments_show_institutions_and_memberships():
    scenario = build_scenario()
    institution_id, _service_id = _institution(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOfInstitution(rank="member"), institution_id)

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert any("Institution nearby: Burrow Cartographers" in line for line in fragments)
    assert any("Institution membership: Burrow Cartographers" in line for line in fragments)


def test_daggersim_fragments_show_nearby_services_magic_law_and_character_state():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(StreetwiseSkillComponent(level=3))
    character.add_component(CustomClassComponent(class_name="Night Gardener"))
    character.add_component(
        SupernaturalAfflictionComponent(
            affliction_type="moon-form", contracted_at_epoch=0, stage="active"
        )
    )
    character.add_component(FeedingNeedComponent(current=4.0, maximum=10.0))
    character.add_component(RecallAnchorComponent(room_id=str(scenario.room_b)))
    nearby = [
        [
            IdentityComponent(name="Moss Bank", kind="bank"),
            BankComponent(name="Moss Bank"),
        ],
        [
            IdentityComponent(name="bank loan", kind="loan"),
            LoanComponent(
                bank_id=str(scenario.room_a),
                borrower_id=str(scenario.character),
                principal=25,
                balance=10,
                due_at_epoch=500,
            ),
        ],
        [
            IdentityComponent(name="trespass charge", kind="crime-record"),
            CrimeRecordComponent(crime_type="trespass", region_id="moss-road", fine=5),
        ],
        [
            IdentityComponent(name="Ranger", kind="class-template"),
            ClassTemplateComponent(class_name="Ranger"),
        ],
        [
            IdentityComponent(name="Mend", kind="spell-template"),
            SpellTemplateComponent(spell_name="Mend", effect_type="heal", magnitude=5),
        ],
        [
            IdentityComponent(name="Moon Mend", kind="spell"),
            CustomSpellComponent(spell_name="Moon Mend", effect_type="heal", magnitude=7),
        ],
        [
            IdentityComponent(name="silver spoon", kind="item"),
            EnchantedItemComponent(spell_name="Gleam", effect_type="light", magnitude=1),
        ],
        [
            IdentityComponent(name="burrow spriggan", kind="creature"),
            CreatureLanguageComponent(language="sylvan"),
            HostilityComponent(hostile=False),
        ],
        [
            IdentityComponent(name="quest board", kind="quest-template"),
            QuestTemplateComponent(
                title="Gather Moon Carrots",
                objective="gather",
                reward_item_name="moon carrot",
            ),
        ],
        [
            IdentityComponent(name="Gather Moon Carrots", kind="quest"),
            GeneratedQuestComponent(title="Gather Moon Carrots", objective="gather"),
        ],
        [
            IdentityComponent(name="Sunken Library", kind="dungeon"),
            DungeonComponent(dungeon_id="sunken-library", theme="ruin", seed="sl"),
        ],
        [
            IdentityComponent(name="loose stone", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(scenario.room_b), hint="cold air", found=True),
        ],
        [
            IdentityComponent(name="moon key", kind="objective"),
            DungeonObjectiveComponent(objective_kind="key", description="a moon key", found=True),
        ],
        [
            IdentityComponent(name="Baroness Thistledown", kind="character"),
            CharacterComponent(species="bunny"),
            SocialRegisterComponent(register="court"),
            ConversationToneComponent(tone="cool", last_reaction="faux-pas"),
        ],
    ]
    for components in nearby:
        entity = spawn_entity(scenario.actor.world, components)
        scenario.actor.world.get_entity(scenario.room_a).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
        )
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        RestRiskComponent(band="uneasy")
    )

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert "Bank nearby: Moss Bank." in fragments
    assert "Loan: 10 due at epoch 500 (active)." in fragments
    assert "Crime record: trespass (open)." in fragments
    assert "Class template available: Ranger." in fragments
    assert "Spell formula available: Mend." in fragments
    assert "Known custom spell: Moon Mend (heal)." in fragments
    assert "Enchanted item: Gleam (light)." in fragments
    assert "Creature language nearby: sylvan (calm)." in fragments
    assert "Work available: Gather Moon Carrots." in fragments
    assert "Generated quest: Gather Moon Carrots (offered)." in fragments
    assert "Dungeon nearby: sunken-library (unexplored)." in fragments
    assert "Secret door found here: cold air." in fragments
    assert "Dungeon objective found: key." in fragments
    assert any("took your last approach faux-pas" in line for line in fragments)
    assert "Rest risk here: uneasy." in fragments
    assert f"Recall anchor set at room {scenario.room_b}." in fragments
    assert "Streetwise skill: 3." in fragments
    assert "Custom class: Night Gardener." in fragments
    assert "Affliction: moon-form (active)." in fragments
    assert "Feeding need: 4.0/10.0." in fragments


def test_daggersim_fragments_cover_suppressed_and_default_states(monkeypatch):
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(TravelHubComponent(name="Self Hub", region_id="moss-road"))
    stale_institution = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Vanished Guild", kind="institution")],
    )
    character.add_relationship(MemberOfInstitution(rank="guest"), stale_institution.id)
    character.add_relationship(MemberOfInstitution(rank="guest"), scenario.room_b)

    suppressed = [
        [
            IdentityComponent(name="Realized Hamlet", kind="settlement"),
            UnrealizedLocationComponent(
                summary="already built",
                region_id="moss-road",
                detail_level="instantiated",
            ),
        ],
        [
            IdentityComponent(name="unheard rumor", kind="rumor"),
            RumorComponent(text="Nobody told you this."),
        ],
        [
            IdentityComponent(name="closed panel", kind="secret-door"),
            SecretDoorComponent(
                target_room_id=str(scenario.room_b),
                hint="cold air",
                found=False,
            ),
        ],
        [
            IdentityComponent(name="hidden key", kind="objective"),
            DungeonObjectiveComponent(objective_kind="key", description="hidden", found=False),
        ],
        [
            IdentityComponent(name="Baroness Thistledown", kind="character"),
            CharacterComponent(species="bunny"),
            ConversationToneComponent(tone="cool", last_reaction=""),
        ],
        [
            IdentityComponent(name="Ferry Gate", kind="travel-hub"),
            TravelHubComponent(name="Ferry Gate", region_id="moss-road"),
        ],
    ]
    visible = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="burrow spriggan", kind="creature"),
            CreatureLanguageComponent(language="sylvan"),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    for components in suppressed:
        entity = spawn_entity(scenario.actor.world, components)
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), visible.id)
    original_has_entity = scenario.actor.world.has_entity

    def has_entity(entity_id):
        if entity_id == stale_institution.id:
            return False
        return original_has_entity(entity_id)

    monkeypatch.setattr(scenario.actor.world, "has_entity", has_entity)

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert "Creature language nearby: sylvan (hostile)." in fragments
    assert "Travel destination: Ferry Gate." in fragments
    assert not any("Nearby unrealized site: Realized Hamlet" in line for line in fragments)
    assert not any("Nobody told you this" in line for line in fragments)
    assert not any("Travel destination: Self Hub" in line for line in fragments)
    assert not any("Secret door found here" in line for line in fragments)
    assert not any("Dungeon objective found" in line for line in fragments)
    assert not any("last approach" in line for line in fragments)
    assert not any("Institution membership" in line for line in fragments)

    room.remove_relationship(Contains, scenario.character)
    assert not any(
        line.startswith("Rest risk here:")
        for line in daggersim_fragments(scenario.actor.world, character)
    )


def _dungeon(scenario, *, generated=True):
    world = scenario.actor.world
    entry_room = spawn_entity(
        world,
        [
            RoomComponent(title="Vault Antechamber"),
            DungeonRoomComponent(dungeon_id="carrot-vault", depth=0),
        ],
    )
    dungeon = spawn_entity(
        world,
        [
            IdentityComponent(name="Carrot Vault", kind="dungeon"),
            DungeonComponent(
                dungeon_id="carrot-vault",
                theme="ruin",
                seed="cv-1",
                entry_room_id=str(entry_room.id),
                generated=generated,
            ),
            ExpansionHookComponent(trigger="quest", generator_plugin_id="worldgen.recursive"),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), dungeon.id
    )
    return dungeon.id, entry_room.id


def _secret_door(scenario, room_id, target_room_id):
    world = scenario.actor.world
    door = spawn_entity(
        world,
        [
            IdentityComponent(name="cracked tiles", kind="secret-door"),
            SecretDoorComponent(
                target_room_id=str(target_room_id),
                direction="down",
                hint="a draft behind the tiles",
            ),
        ],
    )
    world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), door.id
    )
    return door.id


def test_dungeon_handlers_reject_bad_entities_and_components_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong_kind_id = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="loose sign", kind="prop")],
    ).id
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind_id
    )
    generated_dungeon_id, _entry_id = _dungeon(scenario)
    distant_dungeon = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Distant Dungeon", kind="dungeon"),
            DungeonComponent(
                dungeon_id="distant",
                theme="ruin",
                seed="dd",
                generated=True,
            ),
        ],
    )
    missing_entry_dungeon = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Missing Entry", kind="dungeon"),
            DungeonComponent(
                dungeon_id="missing-entry",
                theme="ruin",
                seed="me",
                entry_room_id="entity_999",
                generated=True,
            ),
        ],
    )
    plain_entry = spawn_entity(scenario.actor.world, [RoomComponent(title="Plain Entry")])
    plain_entry_dungeon = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Plain Entry Dungeon", kind="dungeon"),
            DungeonComponent(
                dungeon_id="plain-entry",
                theme="ruin",
                seed="pe",
                entry_room_id=str(plain_entry.id),
                generated=True,
            ),
        ],
    )
    unfound_door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="unfound door", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(scenario.room_b), hint="cold air"),
        ],
    )
    open_door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="open door", kind="secret-door"),
            SecretDoorComponent(
                target_room_id=str(scenario.room_b),
                hint="warm air",
                found=True,
                opened=True,
            ),
        ],
    )
    nowhere_door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="nowhere door", kind="secret-door"),
            SecretDoorComponent(target_room_id="entity_999", hint="empty air", found=True),
        ],
    )
    distant_door = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="distant door", kind="secret-door"),
            SecretDoorComponent(target_room_id=str(scenario.room_b), hint="far air", found=True),
        ],
    )
    for entity_id in (
        missing_entry_dungeon.id,
        plain_entry_dungeon.id,
        unfound_door.id,
        open_door.id,
        nowhere_door.id,
    ):
        scenario.actor.world.get_entity(scenario.room_a).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), entity_id
        )

    for handler, command, reason in (
        (
            RequestDungeonHandler(),
            _handler_cmd(scenario, "request-dungeon", dungeon_id="entity_999"),
            "dungeon does not exist",
        ),
        (
            RequestDungeonHandler(),
            _handler_cmd(scenario, "request-dungeon", dungeon_id=str(wrong_kind_id)),
            "target is not a dungeon",
        ),
        (
            RequestDungeonHandler(),
            _handler_cmd(scenario, "request-dungeon", dungeon_id=str(distant_dungeon.id)),
            "dungeon is not reachable",
        ),
        (
            RequestDungeonHandler(),
            _handler_cmd(scenario, "request-dungeon", dungeon_id=str(generated_dungeon_id)),
            "dungeon is already generated",
        ),
        (
            EnterDungeonHandler(),
            _handler_cmd(scenario, "enter-dungeon", dungeon_id="entity_999"),
            "dungeon does not exist",
        ),
        (
            EnterDungeonHandler(),
            _handler_cmd(scenario, "enter-dungeon", dungeon_id=str(distant_dungeon.id)),
            "dungeon is not reachable",
        ),
        (
            EnterDungeonHandler(),
            _handler_cmd(scenario, "enter-dungeon", dungeon_id=str(wrong_kind_id)),
            "target is not a dungeon",
        ),
        (
            EnterDungeonHandler(),
            _handler_cmd(scenario, "enter-dungeon", dungeon_id=str(missing_entry_dungeon.id)),
            "dungeon has no entry room",
        ),
        (
            EnterDungeonHandler(),
            _handler_cmd(scenario, "enter-dungeon", dungeon_id=str(plain_entry_dungeon.id)),
            "entry is not a dungeon room",
        ),
        (
            SearchRoomHandler(),
            _handler_cmd(scenario, "search-room"),
            "this room cannot be searched",
        ),
        (
            OpenSecretDoorHandler(),
            _handler_cmd(scenario, "open-secret-door", door_id="entity_999"),
            "door does not exist",
        ),
        (
            OpenSecretDoorHandler(),
            _handler_cmd(scenario, "open-secret-door", door_id=str(distant_door.id)),
            "door is not here",
        ),
        (
            OpenSecretDoorHandler(),
            _handler_cmd(scenario, "open-secret-door", door_id=str(wrong_kind_id)),
            "target is not a secret door",
        ),
        (
            OpenSecretDoorHandler(),
            _handler_cmd(scenario, "open-secret-door", door_id=str(unfound_door.id)),
            "door has not been found yet",
        ),
        (
            OpenSecretDoorHandler(),
            _handler_cmd(scenario, "open-secret-door", door_id=str(open_door.id)),
            "door is already open",
        ),
        (
            OpenSecretDoorHandler(),
            _handler_cmd(scenario, "open-secret-door", door_id=str(nowhere_door.id)),
            "door leads nowhere",
        ),
        (
            LeaveDungeonHandler(),
            _handler_cmd(scenario, "leave-dungeon", dungeon_id="entity_999"),
            "dungeon does not exist",
        ),
        (
            LeaveDungeonHandler(),
            _handler_cmd(scenario, "leave-dungeon", dungeon_id=str(wrong_kind_id)),
            "target is not a dungeon",
        ),
        (
            LeaveDungeonHandler(),
            _handler_cmd(scenario, "leave-dungeon", dungeon_id=str(generated_dungeon_id)),
            "not currently in this dungeon",
        ),
    ):
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason


def test_dungeon_utility_handlers_reject_missing_room_or_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )

    for handler, command, reason in (
        (MarkPathHandler(), _handler_cmd(scenario, "mark-path"), "character is not in a room"),
        (SetRecallHandler(), _handler_cmd(scenario, "set-recall"), "character is not in a room"),
        (RestHandler(), _handler_cmd(scenario, "rest"), "character is not in a room"),
    ):
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        scenario.character,
    )
    result = ViewMapHandler().execute(ctx, _handler_cmd(scenario, "view-map"))
    assert result.ok is False
    assert result.reason == "you have no map to view"

    character.add_component(RecallAnchorComponent(room_id="entity_999"))
    result = UseRecallHandler().execute(ctx, _handler_cmd(scenario, "use-recall"))
    assert result.ok is False
    assert result.reason == "recall anchor no longer exists"

    replace_component(character, RecallAnchorComponent(room_id=str(scenario.room_a)))
    result = UseRecallHandler().execute(ctx, _handler_cmd(scenario, "use-recall"))
    assert result.ok is False
    assert result.reason == "already at the recall anchor"

    empty_room = spawn_entity(
        scenario.actor.world,
        [
            RoomComponent(title="Empty Vault"),
            DungeonRoomComponent(dungeon_id="empty-vault", depth=0, discovered=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    empty_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), scenario.character)
    result = SearchRoomHandler().execute(ctx, _handler_cmd(scenario, "search-room"))
    assert result.ok is False
    assert result.reason == "you find nothing of note"


async def test_request_dungeon_marks_generated_and_emits_events():
    scenario = build_scenario()
    _install(scenario.actor)
    dungeon_id, _entry = _dungeon(scenario, generated=False)
    requested: list[DungeonRequestedEvent] = []
    generated: list[DungeonGeneratedEvent] = []
    scenario.actor.bus.subscribe(DungeonRequestedEvent, requested.append)
    scenario.actor.bus.subscribe(DungeonGeneratedEvent, generated.append)

    await scenario.actor.submit(_cmd(scenario, "request-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)

    dungeon = scenario.actor.world.get_entity(dungeon_id).get_component(DungeonComponent)
    assert dungeon.generated is True
    assert requested[0].dungeon_id == "carrot-vault"
    assert requested[0].generator_plugin_id == "worldgen.recursive"
    assert generated[0].dungeon_id == "carrot-vault"


async def test_enter_dungeon_moves_character_and_discovers_entry():
    scenario = build_scenario()
    _install(scenario.actor)
    dungeon_id, entry_id = _dungeon(scenario)
    entered: list[DungeonEnteredEvent] = []
    discovered: list[DungeonRoomDiscoveredEvent] = []
    scenario.actor.bus.subscribe(DungeonEnteredEvent, entered.append)
    scenario.actor.bus.subscribe(DungeonRoomDiscoveredEvent, discovered.append)

    await scenario.actor.submit(_cmd(scenario, "enter-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert container_of(character) == entry_id
    assert entered[0].entry_room_id == str(entry_id)
    assert discovered[0].dungeon_room_id == str(entry_id)
    entry_room = scenario.actor.world.get_entity(entry_id)
    assert entry_room.get_component(DungeonRoomComponent).discovered is True
    assert str(entry_id) in character.get_component(AutomapComponent).discovered_rooms


async def test_enter_dungeon_rejected_until_generated():
    scenario = build_scenario()
    _install(scenario.actor)
    dungeon_id, _entry = _dungeon(scenario, generated=False)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "enter-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "dungeon has not been generated yet" for event in rejects)


async def test_search_room_finds_secret_door_and_objective():
    scenario = build_scenario()
    _install(scenario.actor)
    dungeon_id, entry_id = _dungeon(scenario)
    deeper = spawn_entity(
        scenario.actor.world,
        [
            RoomComponent(title="Inner Vault"),
            DungeonRoomComponent(dungeon_id="carrot-vault", depth=1),
        ],
    )
    door_id = _secret_door(scenario, entry_id, deeper.id)
    objective = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="the carrot reliquary", kind="objective"),
            DungeonObjectiveComponent(objective_kind="relic", description="the lost reliquary"),
        ],
    )
    scenario.actor.world.get_entity(entry_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), objective.id
    )
    doors: list[SecretDoorFoundEvent] = []
    objectives: list[DungeonObjectiveFoundEvent] = []
    scenario.actor.bus.subscribe(SecretDoorFoundEvent, doors.append)
    scenario.actor.bus.subscribe(DungeonObjectiveFoundEvent, objectives.append)

    await scenario.actor.submit(_cmd(scenario, "enter-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "search-room"))
    await scenario.actor.tick(HOUR)

    assert doors[0].door_id == str(door_id)
    assert objectives[0].objective_kind == "relic"
    door = scenario.actor.world.get_entity(door_id).get_component(SecretDoorComponent)
    found_objective = scenario.actor.world.get_entity(objective.id).get_component(
        DungeonObjectiveComponent
    )
    assert door.found
    assert found_objective.found


async def test_open_secret_door_creates_exit_to_target_room():
    scenario = build_scenario()
    _install(scenario.actor)
    dungeon_id, entry_id = _dungeon(scenario)
    deeper = spawn_entity(
        scenario.actor.world,
        [
            RoomComponent(title="Inner Vault"),
            DungeonRoomComponent(dungeon_id="carrot-vault", depth=1),
        ],
    )
    door_id = _secret_door(scenario, entry_id, deeper.id)

    await scenario.actor.submit(_cmd(scenario, "enter-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "search-room"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "open-secret-door", door_id=str(door_id)))
    await scenario.actor.tick(HOUR)

    door = scenario.actor.world.get_entity(door_id).get_component(SecretDoorComponent)
    assert door.opened is True
    entry_room = scenario.actor.world.get_entity(entry_id)
    targets = [target_id for _edge, target_id in entry_room.get_relationships(ExitTo)]
    assert deeper.id in targets


async def test_recall_anchor_set_and_use_returns_to_anchor():
    scenario = build_scenario()
    _install(scenario.actor)
    anchors: list[RecallAnchorSetEvent] = []
    used: list[RecallUsedEvent] = []
    scenario.actor.bus.subscribe(RecallAnchorSetEvent, anchors.append)
    scenario.actor.bus.subscribe(RecallUsedEvent, used.append)

    await scenario.actor.submit(_cmd(scenario, "set-recall"))
    await scenario.actor.tick(HOUR)
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(RecallAnchorComponent).room_id == str(scenario.room_a)

    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(Contains, character.id)
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), character.id
    )

    await scenario.actor.submit(_cmd(scenario, "use-recall"))
    await scenario.actor.tick(HOUR)

    assert container_of(character) == scenario.room_a
    assert anchors[0].anchor_room_id == str(scenario.room_a)
    assert used[0].anchor_room_id == str(scenario.room_a)


async def test_rest_rejected_in_dangerous_room():
    scenario = build_scenario()
    _install(scenario.actor)
    scenario.actor.world.get_entity(scenario.room_a).add_component(
        RestRiskComponent(band="high", note="goblins prowl here")
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "rest"))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "this area is too dangerous to rest" for event in rejects)


async def test_rest_allowed_in_safe_room():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "rest"))
    await scenario.actor.tick(HOUR)

    assert rejects == []


async def test_mark_path_records_breadcrumb_and_view_map_accepted():
    scenario = build_scenario()
    _install(scenario.actor)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "mark-path"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "view-map"))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    automap = character.get_component(AutomapComponent)
    assert str(scenario.room_a) in automap.marked_rooms
    assert rejects == []


async def test_leave_dungeon_clears_entered_and_emits_event():
    scenario = build_scenario()
    _install(scenario.actor)
    dungeon_id, _entry = _dungeon(scenario)
    exited: list[DungeonExitedEvent] = []
    scenario.actor.bus.subscribe(DungeonExitedEvent, exited.append)

    await scenario.actor.submit(_cmd(scenario, "enter-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "leave-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)

    assert exited[0].dungeon_id == "carrot-vault"
    dungeon = scenario.actor.world.get_entity(dungeon_id).get_component(DungeonComponent)
    assert dungeon.entered is False


async def test_dungeon_fragments_describe_location_and_automap():
    scenario = build_scenario()
    _install(scenario.actor)
    dungeon_id, _entry = _dungeon(scenario)

    await scenario.actor.submit(_cmd(scenario, "enter-dungeon", dungeon_id=str(dungeon_id)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    fragments = daggersim_fragments(scenario.actor.world, character)
    assert any("In dungeon carrot-vault at depth 0" in line for line in fragments)
    assert any("Automap:" in line for line in fragments)


def _install_dialogue(scenario):
    scenario.actor.register_handler(SayHandler())
    scenario.actor.register_handler(TellHandler())
    SocialRegisterReactor(scenario.actor.world).subscribe(scenario.actor.bus)


def _listener(scenario, *, register, expected, threshold=3):
    listener = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Baroness Thistledown", kind="character"),
            CharacterComponent(species="bunny"),
            SocialRegisterComponent(
                register=register, expected_approaches=tuple(expected), skill_threshold=threshold
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), listener.id
    )
    return listener.id


async def test_say_with_fitting_approach_is_well_received():
    scenario = build_scenario()
    _install_dialogue(scenario)
    listener_id = _listener(scenario, register="court", expected=("courtly", "formal"))

    await scenario.actor.submit(_cmd(scenario, "say", text="My lady.", approach="courtly"))
    await scenario.actor.tick(HOUR)

    tone = scenario.actor.world.get_entity(listener_id).get_component(ConversationToneComponent)
    assert tone.last_reaction == "well-received"
    assert tone.tone == "warm"
    assert tone.last_approach == "courtly"


async def test_say_with_clashing_approach_is_faux_pas():
    scenario = build_scenario()
    _install_dialogue(scenario)
    listener_id = _listener(scenario, register="court", expected=("courtly", "formal"))

    await scenario.actor.submit(_cmd(scenario, "say", text="Oi.", approach="blunt"))
    await scenario.actor.tick(HOUR)

    tone = scenario.actor.world.get_entity(listener_id).get_component(ConversationToneComponent)
    assert tone.last_reaction == "faux-pas"
    assert tone.tone == "cool"


async def test_high_etiquette_smooths_over_clashing_approach():
    scenario = build_scenario()
    _install_dialogue(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EtiquetteSkillComponent(level=5))
    listener_id = _listener(scenario, register="court", expected=("courtly",), threshold=3)

    await scenario.actor.submit(_cmd(scenario, "say", text="Good day.", approach="formal"))
    await scenario.actor.tick(HOUR)

    tone = scenario.actor.world.get_entity(listener_id).get_component(ConversationToneComponent)
    assert tone.last_reaction == "smoothed"
    assert tone.tone == "neutral"


async def test_streetwise_smooths_over_underworld_approach():
    scenario = build_scenario()
    _install_dialogue(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(StreetwiseSkillComponent(level=4))
    listener_id = _listener(scenario, register="court", expected=("courtly",), threshold=3)

    await scenario.actor.submit(_cmd(scenario, "say", text="Word is...", approach="underworld"))
    await scenario.actor.tick(HOUR)

    tone = scenario.actor.world.get_entity(listener_id).get_component(ConversationToneComponent)
    assert tone.last_reaction == "smoothed"


async def test_tell_records_speaker_last_approach():
    scenario = build_scenario()
    _install_dialogue(scenario)
    listener_id = _listener(scenario, register="court", expected=("polite",))

    await scenario.actor.submit(
        _cmd(scenario, "tell", target_id=str(listener_id), text="Please.", approach="polite")
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(DialogueApproachComponent).last_approach == "polite"
    tone = scenario.actor.world.get_entity(listener_id).get_component(ConversationToneComponent)
    assert tone.last_reaction == "well-received"


async def test_speech_without_approach_leaves_tone_untouched():
    scenario = build_scenario()
    _install_dialogue(scenario)
    listener_id = _listener(scenario, register="court", expected=("courtly",))

    await scenario.actor.submit(_cmd(scenario, "say", text="Hello there."))
    await scenario.actor.tick(HOUR)

    listener = scenario.actor.world.get_entity(listener_id)
    assert not listener.has_component(ConversationToneComponent)


def test_dialogue_fragments_surface_register_and_skills():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EtiquetteSkillComponent(level=2))
    _listener(scenario, register="court", expected=("courtly",))

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert any("Etiquette skill: 2" in line for line in fragments)
    assert any("Social register of Baroness Thistledown: court" in line for line in fragments)


def test_social_register_reactor_ignores_invalid_or_unregistered_listeners():
    scenario = build_scenario()
    reactor = SocialRegisterReactor(scenario.actor.world)
    prop = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="silent marker", kind="prop")],
    )

    reactor._react("not-an-entity", "polite", 0)
    reactor._react(str(prop.id), "polite", 0)

    assert not prop.has_component(ConversationToneComponent)


def test_install_daggersim_registers_plugin_consequences():
    scenario = build_scenario()
    before = len(scenario.actor._consequences)

    install_daggersim(scenario.actor)

    registered = {
        type(consequence).__name__ for consequence in scenario.actor._consequences[before:]
    }
    assert registered == {
        "TravelCompletionConsequence",
        "QuestDeadlineConsequence",
        "LoanDueConsequence",
        "FeedingNeedConsequence",
    }


def _afflicted(scenario, affliction_type="vampire", *, feeding=5.0, transformed=False):
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        SupernaturalAfflictionComponent(
            affliction_type=affliction_type, contracted_at_epoch=0, stage="active"
        )
    )
    character.add_component(FeedingNeedComponent(current=feeding, last_updated_epoch=0))
    if transformed:
        character.add_component(
            WereformComponent(form_name=affliction_type, transformed_at_epoch=0)
        )
    return character


def _victim(scenario, name="Wanderer"):
    victim = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="character"), CharacterComponent(species="bunny")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), victim.id
    )
    return victim.id


async def test_feed_on_target_satisfies_feeding_need():
    scenario = build_scenario()
    _install(scenario.actor)
    _afflicted(scenario, feeding=8.0)
    victim = _victim(scenario)
    feeding: list[FeedingNeedChangedEvent] = []
    scenario.actor.bus.subscribe(FeedingNeedChangedEvent, feeding.append)

    await scenario.actor.submit(_cmd(scenario, "feed-on", target_id=str(victim)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(FeedingNeedComponent).current == 0.0
    assert feeding and feeding[-1].current == 0.0


async def test_end_transformation_reverts_to_dormant():
    scenario = build_scenario()
    _install(scenario.actor)
    _afflicted(scenario, transformed=True)
    ended: list[TransformationEndedEvent] = []
    scenario.actor.bus.subscribe(TransformationEndedEvent, ended.append)

    await scenario.actor.submit(_cmd(scenario, "end-transformation"))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(WereformComponent)
    assert character.get_component(SupernaturalAfflictionComponent).stage == "dormant"
    assert ended and ended[0].affliction_type == "vampire"


async def test_cure_affliction_removes_curse_and_feeding_need():
    scenario = build_scenario()
    _install(scenario.actor)
    _afflicted(scenario, transformed=True)
    cured: list[AfflictionCuredEvent] = []
    scenario.actor.bus.subscribe(AfflictionCuredEvent, cured.append)

    await scenario.actor.submit(_cmd(scenario, "cure-affliction"))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert not character.has_component(SupernaturalAfflictionComponent)
    assert not character.has_component(FeedingNeedComponent)
    assert not character.has_component(WereformComponent)
    assert cured and cured[0].affliction_type == "vampire"


def test_curse_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    victim = _victim(scenario)

    cases = [
        (FeedOnHandler(), _handler_cmd(scenario, "feed-on", character_id="x"), "invalid character"),
        (
            FeedOnHandler(),
            _handler_cmd(scenario, "feed-on", target_id=str(victim)),
            "no feeding need",
        ),
        (
            EndTransformationHandler(),
            _handler_cmd(scenario, "end-transformation", character_id="x"),
            "invalid character",
        ),
        (
            EndTransformationHandler(),
            _handler_cmd(scenario, "end-transformation"),
            "not transformed",
        ),
        (
            CureAfflictionHandler(),
            _handler_cmd(scenario, "cure-affliction", character_id="x"),
            "invalid character",
        ),
        (
            CureAfflictionHandler(),
            _handler_cmd(scenario, "cure-affliction"),
            "no supernatural affliction",
        ),
    ]
    for handler, command, expected in cases:
        result = handler.execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)

    # With an affliction, feed-on still validates the target.
    _afflicted(scenario)
    far_victim = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far soul", kind="character"), CharacterComponent(species="bunny")],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), far_victim.id
    )
    feed_cases = [
        (_handler_cmd(scenario, "feed-on", target_id=str(scenario.character)), "yourself"),
        (_handler_cmd(scenario, "feed-on"), "invalid feeding target"),
        (_handler_cmd(scenario, "feed-on", target_id="ghost_1"), "does not exist"),
        (_handler_cmd(scenario, "feed-on", target_id=str(far_victim.id)), "not reachable"),
    ]
    for command, expected in feed_cases:
        result = FeedOnHandler().execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_daggersim_fragments_show_transformed_state():
    scenario = build_scenario()
    _install(scenario.actor)
    _afflicted(scenario, transformed=True)

    lines = daggersim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )
    assert any("Transformed into vampire" in line for line in lines)


def _first_and_observer_contexts(world, entity, character):
    """Build (first-person, observer) prompt contexts for an entity vs. character."""
    observer = spawn_entity(world, [CharacterComponent()])
    first = ComponentPromptContext.for_entity(
        world,
        entity,
        perspective=PromptPerspective(viewer=character),
        target=character,
    )
    observer_ctx = ComponentPromptContext.for_entity(
        world,
        entity,
        perspective=PromptPerspective(viewer=observer),
        target=character,
    )
    return first, observer_ctx


def test_daggersim_first_person_only_fragments_hide_from_observers():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    # carrier entity is the character itself for self-scoped components
    first, observer = _first_and_observer_contexts(world, character, character)

    cases = [
        (
            TravelPlanComponent(
                destination_id="d", started_at_epoch=0, arrive_at_epoch=10, mode="cart"
            ),
            "Traveling by cart; arrival due at epoch 10.",
        ),
        (
            InstitutionReputationComponent(scores={"guild_1": 3}),
            "Institution reputation with guild_1: 3.",
        ),
        (
            LegalReputationComponent(scores={"region_a": -2}),
            "Legal reputation in region_a: -2.",
        ),
        (
            ServiceAccessComponent(service_ids=("svc_1", "svc_2")),
            "Unlocked institution services: 2.",
        ),
        (
            CustomClassComponent(class_name="Tunnel Sage"),
            "Custom class: Tunnel Sage.",
        ),
        (
            SupernaturalAfflictionComponent(affliction_type="vampire", contracted_at_epoch=0),
            "Affliction: vampire (incubating).",
        ),
        (
            AfflictionStigmaComponent(region_id="moss-road", severity=4),
            "Affliction stigma: moss-road severity 4.",
        ),
        (
            CureQuestHookComponent(affliction_type="vampire"),
            "Cure quest hook: vampire.",
        ),
        (
            FeedingNeedComponent(current=3.0, maximum=10.0),
            "Feeding need: 3.0/10.0.",
        ),
        (
            WereformComponent(form_name="wolf", transformed_at_epoch=0),
            "Transformed into wolf.",
        ),
        (
            AutomapComponent(discovered_rooms=("r1", "r2", "r3")),
            "Automap: 3 room(s) discovered.",
        ),
        (
            RecallAnchorComponent(room_id="room_x"),
            "Recall anchor set at room room_x.",
        ),
        (
            EtiquetteSkillComponent(level=7),
            "Etiquette skill: 7.",
        ),
        (
            StreetwiseSkillComponent(level=5),
            "Streetwise skill: 5.",
        ),
    ]
    for component, expected in cases:
        assert component.prompt_fragments(first) == (expected,), component
        assert component.prompt_fragments(observer) == (), component


def test_daggersim_service_directory_and_membership_fragments():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    self_ctx = ComponentPromptContext.for_entity(world, character)

    # InstitutionServiceComponent: with and without deed-tag requirement.
    plain = InstitutionServiceComponent(service_name="ferry pass")
    assert plain.prompt_fragments(self_ctx) == ("Service directory entry: ferry pass.",)
    gated = InstitutionServiceComponent(
        service_name="charter",
        required_deed_tag="heroism",
        required_deed_score=2.5,
    )
    assert gated.prompt_fragments(self_ctx) == (
        "Service directory entry: charter requires heroism deed reputation 2.5.",
    )

    # MemberOfInstitution edge fragment is first-person only, target must be an institution.
    institution = spawn_entity(world, [InstitutionComponent(name="Burrow Cartographers")])
    edge = MemberOfInstitution(rank="cartographer")
    member_ctx = ComponentPromptContext.for_entity(
        world, character, perspective=self_ctx.perspective, target=institution
    )
    assert edge.prompt_fragments(member_ctx) == (
        "Institution membership: Burrow Cartographers (cartographer).",
    )
    # Observer perspective hides it.
    observer = spawn_entity(world, [CharacterComponent()])
    observer_ctx = ComponentPromptContext.for_entity(
        world, character, perspective=PromptPerspective(viewer=observer), target=institution
    )
    assert edge.prompt_fragments(observer_ctx) == ()
    # First-person but target is not an institution -> empty.
    non_institution = spawn_entity(world, [IdentityComponent(name="rock", kind="item")])
    non_inst_ctx = ComponentPromptContext.for_entity(
        world, character, perspective=self_ctx.perspective, target=non_institution
    )
    assert edge.prompt_fragments(non_inst_ctx) == ()


def test_daggersim_travel_interruption_and_class_template_fragments():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    ctx = ComponentPromptContext.for_entity(world, character)

    assert TravelInterruptionComponent(reason="storm").prompt_fragments(ctx) == (
        "Travel interruption: storm (unresolved).",
    )
    assert TravelInterruptionComponent(reason="storm", resolved=True).prompt_fragments(ctx) == (
        "Travel interruption: storm (resolved).",
    )
    assert ClassTemplateComponent(class_name="Tunnel Sage").prompt_fragments(ctx) == (
        "Class template available: Tunnel Sage.",
    )
    assert RestRiskComponent(band="high").prompt_fragments(ctx) == ("Rest risk here: high.",)
    assert DungeonRoomComponent(dungeon_id="dgn", depth=2).prompt_fragments(ctx) == (
        "In dungeon dgn at depth 2.",
    )


def test_daggersim_dungeon_and_secret_door_fragments_state_dependent():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    other = spawn_entity(world, [CharacterComponent()])

    # Dungeon nearby is shown when the entity is not the target.
    dungeon_entity = spawn_entity(world, [DungeonComponent(dungeon_id="crypt")])
    nearby_ctx = ComponentPromptContext.for_entity(
        world, dungeon_entity, perspective=PromptPerspective(viewer=character), target=character
    )
    assert DungeonComponent(dungeon_id="crypt").prompt_fragments(nearby_ctx) == (
        "Dungeon nearby: crypt (unexplored).",
    )
    assert DungeonComponent(dungeon_id="crypt", entered=True).prompt_fragments(nearby_ctx) == (
        "Dungeon nearby: crypt (explored).",
    )
    # When the dungeon entity IS the target it is suppressed.
    self_target_ctx = ComponentPromptContext.for_entity(
        world,
        dungeon_entity,
        perspective=PromptPerspective(viewer=other),
        target=dungeon_entity,
    )
    assert DungeonComponent(dungeon_id="crypt").prompt_fragments(self_target_ctx) == ()

    # DungeonObjective only shows when found.
    obj_ctx = ComponentPromptContext.for_entity(world, character)
    assert DungeonObjectiveComponent(objective_kind="idol").prompt_fragments(obj_ctx) == ()
    assert DungeonObjectiveComponent(
        objective_kind="idol", found=True
    ).prompt_fragments(obj_ctx) == ("Dungeon objective found: idol.",)

    # SecretDoor shows only when found and not yet opened.
    assert SecretDoorComponent(target_room_id="r").prompt_fragments(obj_ctx) == ()
    assert SecretDoorComponent(
        target_room_id="r", found=True, hint="loose brick"
    ).prompt_fragments(obj_ctx) == ("Secret door found here: loose brick.",)
    assert SecretDoorComponent(
        target_room_id="r", found=True, opened=True
    ).prompt_fragments(obj_ctx) == ()


def test_daggersim_social_register_and_conversation_tone_fragments():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    speaker = spawn_entity(world, [IdentityComponent(name="Reeve Tamsin", kind="character")])

    # SocialRegister of another entity is shown; suppressed when entity is the target.
    nearby_ctx = ComponentPromptContext.for_entity(
        world, speaker, perspective=PromptPerspective(viewer=character), target=character
    )
    assert SocialRegisterComponent(register="courtly").prompt_fragments(nearby_ctx) == (
        "Social register of Reeve Tamsin: courtly.",
    )
    self_target_ctx = ComponentPromptContext.for_entity(
        world, speaker, perspective=PromptPerspective(viewer=character), target=speaker
    )
    assert SocialRegisterComponent(register="courtly").prompt_fragments(self_target_ctx) == ()

    # ConversationTone: no last reaction -> empty.
    assert ConversationToneComponent().prompt_fragments(nearby_ctx) == ()
    # Suppressed when the toned entity is the target itself.
    assert ConversationToneComponent(
        tone="warm", last_reaction="well"
    ).prompt_fragments(self_target_ctx) == ()
    # Shown to the addressed viewer (can_view_private_state via target==viewer).
    addressed_ctx = ComponentPromptContext.for_entity(
        world, speaker, perspective=PromptPerspective(viewer=character), target=character
    )
    assert ConversationToneComponent(
        tone="warm", last_reaction="well"
    ).prompt_fragments(addressed_ctx) == (
        "Reeve Tamsin took your last approach well (tone: warm).",
    )
    # Hidden from a third-party observer (cannot view private state).
    third = spawn_entity(world, [CharacterComponent()])
    third_ctx = ComponentPromptContext.for_entity(
        world, speaker, perspective=PromptPerspective(viewer=third), target=character
    )
    assert ConversationToneComponent(
        tone="warm", last_reaction="well"
    ).prompt_fragments(third_ctx) == ()


def test_daggersim_owns_property_fragment_requires_target():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    self_ctx = ComponentPromptContext.for_entity(world, character)
    # First-person but no target -> empty (line 416 path).
    no_target = ComponentPromptContext.for_entity(
        world, character, perspective=self_ctx.perspective, target=None
    )
    assert OwnsProperty(deed_id="deed").prompt_fragments(no_target) == ()


def test_daggersim_payload_entity_id_and_route_helpers():
    scenario = build_scenario()
    world = scenario.actor.world
    command = _cmd(scenario, "noop")
    # No matching key -> None (line 41).
    assert _payload_entity_id(command, "missing_key") is None
    keyed = _cmd(scenario, "noop", target_id="not-a-real-id")
    assert _payload_entity_id(keyed, "target_id") is None

    # _route_between returns None when no TravelRoute matches the destination.
    origin = world.get_entity(scenario.room_a)
    other = world.get_entity(scenario.room_b)
    assert _route_between(origin, other.id) is None
    origin.add_relationship(TravelRoute(travel_seconds=60, label="moss road"), other.id)
    found = _route_between(origin, other.id)
    assert found is not None and found.label == "moss road"


def test_daggersim_fragments_include_legal_reputation_and_named_institution():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    institution = spawn_entity(
        world,
        [
            IdentityComponent(name="Coin Wardens", kind="institution"),
            InstitutionComponent(name="Coin Wardens"),
        ],
    )
    # InstitutionReputationComponent with a resolvable entity id -> uses its name (4091->4093).
    replace_component(
        character,
        InstitutionReputationComponent(scores={str(institution.id): 6}),
    )
    replace_component(
        character,
        LegalReputationComponent(scores={"moss-road": -3}),
    )
    lines = daggersim_fragments(world, character)
    assert any("Institution reputation with Coin Wardens: 6." == line for line in lines)
    assert any("Legal reputation in moss-road: -3." == line for line in lines)


def test_daggersim_use_service_rejects_non_institution_container():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    # A service whose container is a plain room (not an institution) is invalid (line 1597).
    service = spawn_entity(
        world,
        [
            IdentityComponent(name="floating desk", kind="service"),
            InstitutionServiceComponent(service_name="floating desk"),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), service.id
    )
    result = UseInstitutionServiceHandler().execute(
        ctx, _handler_cmd(scenario, "use-institution-service", service_id=str(service.id))
    )
    assert not result.ok
    assert result.reason == "service institution is invalid"
    del character


def test_daggersim_commit_crime_rejects_blank_crime_type():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = CommitCrimeHandler().execute(
        ctx, _handler_cmd(scenario, "commit-crime", crime_type="   ")
    )
    assert not result.ok
    assert result.reason == "invalid character or crime type"


def test_daggersim_camp_rejects_character_without_room():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    # Detach the character from its room so container_of returns None (line 2673).
    world.get_entity(scenario.room_a).remove_relationship(Contains, scenario.character)
    result = CampHandler().execute(ctx, _handler_cmd(scenario, "camp"))
    assert not result.ok
    assert result.reason == "character is not in a room"


def test_daggersim_search_room_rejects_character_without_room():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    world.get_entity(scenario.room_a).remove_relationship(Contains, scenario.character)
    result = SearchRoomHandler().execute(ctx, _handler_cmd(scenario, "search-room"))
    assert not result.ok
    assert result.reason == "character is not in a room"


def test_daggersim_use_recall_rejects_without_anchor():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    result = UseRecallHandler().execute(ctx, _handler_cmd(scenario, "use-recall"))
    assert not result.ok
    assert result.reason == "no recall anchor is set"


def test_daggersim_pacify_fail_leaves_creature_hostile():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    character.add_component(LanguageSkillComponent(languages={"growl": 0}))
    creature = spawn_entity(
        world,
        [
            IdentityComponent(name="cave bear", kind="creature"),
            CreatureLanguageComponent(language="growl", pacification_difficulty=100),
            HostilityComponent(hostile=True),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), creature.id
    )
    result = AttemptPacifyHandler().execute(
        ctx,
        _handler_cmd(
            scenario, "attempt-pacify", target_id=str(creature.id), language="growl"
        ),
    )
    # Difficulty 100 vs skill 0 => failure; creature stays hostile, not pacified (3222->3248).
    assert result.ok
    refreshed = world.get_entity(creature.id)
    assert refreshed.get_component(HostilityComponent).hostile is True
    assert not refreshed.has_component(PacifiedComponent)


def test_daggersim_pacify_succeeds_on_nonhostile_creature():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    character.add_component(LanguageSkillComponent(languages={"growl": 100}))
    creature = spawn_entity(
        world,
        [
            IdentityComponent(name="shy mole", kind="creature"),
            CreatureLanguageComponent(language="growl", pacification_difficulty=0),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), creature.id
    )
    result = AttemptPacifyHandler().execute(
        ctx,
        _handler_cmd(
            scenario, "attempt-pacify", target_id=str(creature.id), language="growl"
        ),
    )
    # Success path where the creature has no HostilityComponent (3223->3228).
    assert result.ok
    assert world.get_entity(creature.id).has_component(PacifiedComponent)


def test_daggersim_end_transformation_without_affliction():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    # Transformed but with no SupernaturalAfflictionComponent (3458->3462).
    character.add_component(WereformComponent(form_name="wolf", transformed_at_epoch=0))
    result = EndTransformationHandler().execute(
        ctx, _handler_cmd(scenario, "end-transformation")
    )
    assert result.ok
    assert not world.get_entity(scenario.character).has_component(WereformComponent)


def test_daggersim_cure_affliction_without_feeding_or_wereform():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    # Affliction present but no FeedingNeed / Wereform (3488->3490, 3490->3492).
    character.add_component(
        SupernaturalAfflictionComponent(affliction_type="ghoul", contracted_at_epoch=0)
    )
    result = CureAfflictionHandler().execute(ctx, _handler_cmd(scenario, "cure-affliction"))
    assert result.ok
    assert not world.get_entity(scenario.character).has_component(
        SupernaturalAfflictionComponent
    )


def test_daggersim_rest_allows_low_risk_area():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    room = world.get_entity(scenario.room_a)
    room.add_component(RestRiskComponent(band="low"))
    # Low-risk band is not high/ambush, so rest is allowed (3979->3981).
    result = RestHandler().execute(ctx, _handler_cmd(scenario, "rest"))
    assert result.ok


def test_daggersim_withdraw_and_string_tuple_and_identify_can_handle():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)

    # _string_tuple over a comma string (line 3536).
    assert _string_tuple("a, b ,, c", ()) == ("a", "b", "c")

    # IdentifyIngredientHandler.can_handle resolves via target_id when ingredient_id absent.
    ingredient = spawn_entity(
        world,
        [
            IdentityComponent(name="moss sprig", kind="ingredient"),
            IngredientComponent(ingredient_name="mossbane"),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), ingredient.id
    )
    handler = IdentifyIngredientHandler()
    assert handler.can_handle(
        ctx, _handler_cmd(scenario, "identify", target_id=str(ingredient.id))
    )

    # Withdraw success path (lines 2127-2129).
    bank_id = _bank(scenario)
    OpenBankAccountHandler().execute(
        ctx, _handler_cmd(scenario, "open-bank-account", bank_id=str(bank_id))
    )
    DepositHandler().execute(
        ctx, _handler_cmd(scenario, "deposit", bank_id=str(bank_id), amount=10)
    )
    result = WithdrawHandler().execute(
        ctx, _handler_cmd(scenario, "withdraw", bank_id=str(bank_id), amount=4)
    )
    assert result.ok
    del character


def _put_character_in_dungeon_room(scenario):
    """Place the character in a fresh, undiscovered dungeon room."""
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    world.get_entity(scenario.room_a).remove_relationship(Contains, character.id)
    dungeon_room = spawn_entity(
        world,
        [
            IdentityComponent(name="Vault Antechamber", kind="room"),
            RoomComponent(title="Vault Antechamber"),
            DungeonRoomComponent(dungeon_id="vault", depth=1),
        ],
    )
    dungeon_room.add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), character.id
    )
    return dungeon_room


def test_daggersim_search_room_discovers_door_and_objective():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    dungeon_room = _put_character_in_dungeon_room(scenario)
    door = spawn_entity(
        world,
        [SecretDoorComponent(target_room_id="r2", hint="cracked tile")],
    )
    objective = spawn_entity(
        world,
        [DungeonObjectiveComponent(objective_kind="idol")],
    )
    dungeon_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), door.id)
    dungeon_room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), objective.id)

    result = SearchRoomHandler().execute(ctx, _handler_cmd(scenario, "search-room"))
    assert result.ok
    # Fresh room gets discovered + noted on automap (lines 3778-3779).
    character = world.get_entity(scenario.character)
    assert world.get_entity(dungeon_room.id).get_component(DungeonRoomComponent).discovered
    assert str(dungeon_room.id) in character.get_component(AutomapComponent).discovered_rooms
    assert world.get_entity(door.id).get_component(SecretDoorComponent).found
    assert world.get_entity(objective.id).get_component(DungeonObjectiveComponent).found

    # Searching again: room already discovered, door & objective already found
    # (branches 3796->3810, 3812->3792 take the "already found" path).
    again = SearchRoomHandler().execute(ctx, _handler_cmd(scenario, "search-room"))
    assert not again.ok
    assert again.reason == "you find nothing of note"


def test_daggersim_use_recall_moves_character_to_anchor():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    anchor = world.get_entity(scenario.room_b)
    character.add_component(RecallAnchorComponent(room_id=str(anchor.id)))
    result = UseRecallHandler().execute(ctx, _handler_cmd(scenario, "use-recall"))
    assert result.ok
    assert container_of(world.get_entity(scenario.character)) == anchor.id


def test_daggersim_route_between_skips_non_matching_routes():
    scenario = build_scenario()
    world = scenario.actor.world
    origin = world.get_entity(scenario.room_a)
    decoy = spawn_entity(world, [RoomComponent(title="Decoy")])
    destination = world.get_entity(scenario.room_b)
    # First edge does not match the destination, forcing the loop to continue (1507->1506).
    origin.add_relationship(TravelRoute(travel_seconds=30, label="decoy path"), decoy.id)
    origin.add_relationship(TravelRoute(travel_seconds=60, label="real path"), destination.id)
    route = _route_between(origin, destination.id)
    assert route is not None and route.label == "real path"


def test_daggersim_identify_can_handle_via_ingredient_id():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    # ingredient_id present in payload short-circuits to True (line 3114).
    assert IdentifyIngredientHandler().can_handle(
        ctx, _handler_cmd(scenario, "identify", ingredient_id="anything")
    )


def test_daggersim_send_debt_collector_without_borrower_room():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    # Borrower (the acting character) is not in any room (2434->2438).
    world.get_entity(scenario.room_a).remove_relationship(Contains, scenario.character)
    debt = spawn_entity(world, [DebtComponent(amount=10, defaulted_at_epoch=0)])
    result = SendDebtCollectorHandler().execute(
        ctx, _handler_cmd(scenario, "send-debt-collector", debt_id=str(debt.id))
    )
    assert result.ok


def test_daggersim_selected_rumor_skips_already_heard():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    room = world.get_entity(scenario.room_a)
    # When every reachable rumor is already heard, auto-select skips them all and
    # returns None. With nothing to match, every iteration takes the skip back-edge
    # (3609->3604) regardless of the reachable-set iteration order — this pins the
    # branch that otherwise only flaked when a heard rumor happened to precede a fresh
    # one in set order (see PYTHONHASHSEED-sensitive coverage).
    heard = spawn_entity(
        world, [RumorComponent(text="old news", heard_by=(str(scenario.character),))]
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), heard.id)
    assert _selected_rumor_id(ctx, scenario.character, None) is None

    # Adding a fresh rumor makes auto-select return it (the match return, 3609->3610).
    fresh = spawn_entity(world, [RumorComponent(text="fresh tip")])
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), fresh.id)
    assert _selected_rumor_id(ctx, scenario.character, None) == fresh.id


@settings(max_examples=50, deadline=None, derandomize=True)
@given(heard_flags=st.lists(st.booleans(), min_size=1, max_size=6))
def test_daggersim_selected_rumor_is_order_independent(heard_flags):
    # Property: auto-select returns some unheard reachable rumor when one exists, else
    # None — no matter how many already-heard rumors are present or what order the
    # reachable set yields them in. The all-heard examples drive the skip back-edge and
    # the mixed examples drive the match return across many set orderings, generalizing
    # the single hand-built case above (this is the "seed testing" hypothesis covers).
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    room = world.get_entity(scenario.room_a)
    character_key = str(scenario.character)
    unheard_ids = set()
    for index, already_heard in enumerate(heard_flags):
        heard_by = (character_key,) if already_heard else ()
        rumor = spawn_entity(
            world, [RumorComponent(text=f"rumor-{index}", heard_by=heard_by)]
        )
        room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), rumor.id)
        if not already_heard:
            unheard_ids.add(rumor.id)

    selected = _selected_rumor_id(ctx, scenario.character, None)

    if unheard_ids:
        assert selected in unheard_ids
    else:
        assert selected is None


def test_daggersim_use_recall_from_roomless_character():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    character = world.get_entity(scenario.character)
    anchor = world.get_entity(scenario.room_b)
    character.add_component(RecallAnchorComponent(room_id=str(anchor.id)))
    # Detach the character from any room so _move_character sees no origin (3616->3618).
    world.get_entity(scenario.room_a).remove_relationship(Contains, character.id)
    result = UseRecallHandler().execute(ctx, _handler_cmd(scenario, "use-recall"))
    assert result.ok
    assert container_of(world.get_entity(scenario.character)) == anchor.id


def test_daggersim_fragments_keep_unresolvable_reputation_label():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    # InstitutionReputation keyed by a non-entity string keeps the raw label (4092->4094).
    replace_component(
        character, InstitutionReputationComponent(scores={"not-an-entity": 4})
    )
    lines = daggersim_fragments(world, character)
    assert any("Institution reputation with not-an-entity: 4." == line for line in lines)


def test_daggersim_social_register_reactor_ignores_missing_speaker():
    scenario = build_scenario()
    world = scenario.actor.world
    reactor = SocialRegisterReactor(world)
    listener = spawn_entity(
        world,
        [
            IdentityComponent(name="Reeve", kind="character"),
            SocialRegisterComponent(register="courtly", expected_approaches=("courtly",)),
        ],
    )
    from datetime import UTC, datetime
    from uuid import uuid4

    event = SpeechSaidEvent(
        event_id=uuid4().hex,
        world_epoch=0,
        created_at=datetime.now(UTC),
        actor_id="not-a-real-entity",
        target_ids=(str(listener.id),),
        text="oi",
        approach="blunt",
    )
    # speaker is None, so the DialogueApproach write is skipped (speaker-guard branch);
    # the listener still reacts to the clashing approach with skill level 0.
    reactor._on_speech(event)
    assert world.get_entity(listener.id).has_component(ConversationToneComponent)


def test_daggersim_mark_path_twice_keeps_single_discovery():
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    ctx = HandlerContext(world, scenario.actor.epoch)
    room_id = str(scenario.room_a)
    assert MarkPathHandler().execute(ctx, _handler_cmd(scenario, "mark-path")).ok
    # Second mark: the room is already in discovered_rooms (branch 3639->3641).
    assert MarkPathHandler().execute(ctx, _handler_cmd(scenario, "mark-path")).ok
    automap = world.get_entity(scenario.character).get_component(AutomapComponent)
    assert automap.discovered_rooms.count(room_id) == 1
    assert automap.marked_rooms.count(room_id) == 1


def test_daggersim_fragments_skip_owned_property_when_entity_gone(monkeypatch):
    scenario = build_scenario()
    _install(scenario.actor)
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    property_entity = spawn_entity(
        world, [IdentityComponent(name="Vanished Loft", kind="home")]
    )
    character.add_relationship(OwnsProperty(deed_id="d"), property_entity.id)
    original_has_entity = world.has_entity

    def has_entity(entity_id):
        if entity_id == property_entity.id:
            return False
        return original_has_entity(entity_id)

    monkeypatch.setattr(world, "has_entity", has_entity)
    lines = daggersim_fragments(world, character)
    # The owned-property edge is skipped because the target reads as gone (4105->4104).
    assert not any("Property owned" in line for line in lines)
