"""Tests for dagger-sim procedural RPG realm mechanics."""

from __future__ import annotations

from conftest import build_scenario

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
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import SayHandler, TellHandler
from bunnyland.mechanics.daggersim import (
    AcceptGeneratedQuestHandler,
    AccountOpenedEvent,
    AfflictionContractedEvent,
    AskForWorkHandler,
    AskRumorHandler,
    AttemptPacifyHandler,
    AutomapComponent,
    BankAccountComponent,
    BankComponent,
    BountyComponent,
    BountyPostedEvent,
    CastSpellHandler,
    ClassTemplateComponent,
    CommitCrimeHandler,
    CompleteGeneratedQuestHandler,
    ContractAfflictionHandler,
    ConversationToneComponent,
    CreateCustomClassHandler,
    CreateSpellHandler,
    CreatureLanguageComponent,
    CreaturePacifiedEvent,
    CrimeCommittedEvent,
    CrimeRecordComponent,
    CustomClassComponent,
    CustomClassCreatedEvent,
    CustomSpellComponent,
    DaggerQuestRewardComponent,
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
    EnchantItemHandler,
    EnterDungeonHandler,
    EtiquetteSkillComponent,
    ExpandSiteHandler,
    ExpansionHookComponent,
    ExpansionRequestedEvent,
    FeedingNeedChangedEvent,
    FeedingNeedComponent,
    FeedingNeedConsequence,
    FinePaidEvent,
    GeneratedQuestComponent,
    GeneratedSiteInstantiatedEvent,
    HostilityComponent,
    InstitutionComponent,
    InstitutionJoinedEvent,
    InstitutionServiceComponent,
    InstitutionServiceUsedEvent,
    InvestigateRumorHandler,
    ItemEnchantedEvent,
    JoinInstitutionHandler,
    LanguageSkillComponent,
    LawRegionComponent,
    LeaveDungeonHandler,
    LoanComponent,
    LoanDefaultedEvent,
    LoanDueConsequence,
    LoanIssuedEvent,
    LoanRepaidEvent,
    MarkPathHandler,
    MemberOfInstitution,
    OpenBankAccountHandler,
    OpenSecretDoorHandler,
    PacificationAttemptedEvent,
    PacifiedComponent,
    PayFineHandler,
    PlanTravelHandler,
    ProceduralSiteComponent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestDeadlineComponent,
    QuestDeadlineConsequence,
    QuestFailedEvent,
    QuestGeneratedEvent,
    QuestTemplateComponent,
    RecallAnchorComponent,
    RecallAnchorSetEvent,
    RecallUsedEvent,
    RepayLoanHandler,
    RequestDungeonHandler,
    RestHandler,
    RestRiskComponent,
    RumorBecameExpansionEvent,
    RumorComponent,
    RumorHeardEvent,
    RumorReliabilityComponent,
    RumorTargetComponent,
    RumorVerifiedEvent,
    SearchRoomHandler,
    SecretDoorComponent,
    SecretDoorFoundEvent,
    SetRecallHandler,
    SocialRegisterComponent,
    SocialRegisterReactor,
    SpellCastEvent,
    SpellCreatedEvent,
    SpellTemplateComponent,
    StreetwiseSkillComponent,
    SupernaturalAfflictionComponent,
    TakeLoanHandler,
    TransformationStartedEvent,
    TransformHandler,
    TravelCompletedEvent,
    TravelCompletionConsequence,
    TravelHubComponent,
    TravelModeComponent,
    TravelPlanComponent,
    TravelRoute,
    TravelStartedEvent,
    UnrealizedLocationComponent,
    UseInstitutionServiceHandler,
    UseRecallHandler,
    ViewMapHandler,
    WereformComponent,
    WithdrawHandler,
    daggersim_fragments,
)

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
    actor.register_handler(CreateCustomClassHandler())
    actor.register_handler(CreateSpellHandler())
    actor.register_handler(EnchantItemHandler())
    actor.register_handler(CastSpellHandler())
    actor.register_handler(AttemptPacifyHandler())
    actor.register_handler(ContractAfflictionHandler())
    actor.register_handler(TransformHandler())
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


def _institution(scenario, *, required_rank="member"):
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
    scenario.actor.bus.subscribe(InstitutionJoinedEvent, joined.append)
    scenario.actor.bus.subscribe(InstitutionServiceUsedEvent, used.append)

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
    assert joined[0].institution_name == "Burrow Cartographers"
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
    scenario.actor.bus.subscribe(AccountOpenedEvent, opened.append)
    scenario.actor.bus.subscribe(CrimeCommittedEvent, crimes.append)
    scenario.actor.bus.subscribe(BountyPostedEvent, bounties.append)
    scenario.actor.bus.subscribe(FinePaidEvent, paid.append)

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

    await scenario.actor.submit(_cmd(scenario, "pay-fine", crime_id=str(crime_id)))
    await scenario.actor.tick(HOUR)

    account = scenario.actor.world.get_entity(account_id)
    assert account.get_component(BankAccountComponent).balance == 5
    assert crime.get_component(CrimeRecordComponent).status == "paid"
    assert not crime.has_component(BountyComponent)
    assert paid[0].crime_id == str(crime_id)


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


def test_daggersim_fragments_show_institutions_and_memberships():
    scenario = build_scenario()
    institution_id, _service_id = _institution(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOfInstitution(rank="member"), institution_id)

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert any("Institution nearby: Burrow Cartographers" in line for line in fragments)
    assert any("Institution membership: Burrow Cartographers" in line for line in fragments)


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
