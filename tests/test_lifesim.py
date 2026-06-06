"""Tests for life-sim romance, pregnancy, and family mechanics (spec 20.5-20.6)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    ActionPointsComponent,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    ControlledBy,
    DeadComponent,
    DownedComponent,
    HealthComponent,
    IdentityComponent,
    Lane,
    LLMControllerComponent,
    SuspendedComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import (
    AdoptionCompletedEvent,
    BirthDueEvent,
    BirthResolvedEvent,
    CharacterDiedEvent,
    CommandRejectedEvent,
    PartnershipStartedEvent,
)
from bunnyland.mechanics.lifesim import (
    AdoptChildHandler,
    AgeComponent,
    AspirationComponent,
    AssessTaxHandler,
    BillComponent,
    BillPaidEvent,
    BirthDueComponent,
    BusinessOwnerComponent,
    BusinessSaleEvent,
    CareerComponent,
    ChargeRentHandler,
    ChooseAspirationHandler,
    ClaimHomeHandler,
    ClaimRoomHandler,
    CompleteMilestoneHandler,
    CustomerComponent,
    FindJobHandler,
    GossipSpreadEvent,
    GoToWorkHandler,
    HasBill,
    HasRoutine,
    HomeComponent,
    HouseholdComponent,
    HouseholdFundsComponent,
    HouseholdJoinedEvent,
    JealousOf,
    JealousyTriggeredEvent,
    JobScheduleComponent,
    JoinHouseholdHandler,
    LifesimAgingPolicyComponent,
    LifeStageComponent,
    MentorshipCompletedEvent,
    MentorSkillHandler,
    MilestoneCompletedEvent,
    OpenBusinessHandler,
    OwnsBusiness,
    ParentOf,
    PartnerOf,
    PayBillHandler,
    PayWageHandler,
    PracticeSkillHandler,
    PregnancyComponent,
    PromoteBusinessHandler,
    PromotionEarnedEvent,
    QuitJobHandler,
    ReproductiveComponent,
    ReputationComponent,
    ResolveBirthHandler,
    RoomClaimComponent,
    RoutineComponent,
    RoutineDueEvent,
    SellItemHandler,
    SetRelationshipStatusHandler,
    SetRoutineHandler,
    SkillLeveledEvent,
    SkillSetComponent,
    SkillXPChangedEvent,
    SpreadGossipHandler,
    StartPartnershipHandler,
    StartPregnancyHandler,
    StudySkillHandler,
    TaxAssessedEvent,
    WagePaidEvent,
    WitnessRomanceHandler,
    WorkShiftCompletedEvent,
    configure_lifesim_aging,
    install_lifesim,
    kinship_label,
    lifesim_fragments,
)
from bunnyland.mechanics.policy import (
    BoundaryTag,
    CharacterBoundaryComponent,
    install_policy,
)
from bunnyland.persistence import WorldMeta, load_world, save_world

HOUR = 3600.0
LIFE_TAGS = frozenset({BoundaryTag.ROMANCE, BoundaryTag.ADULT, BoundaryTag.PREGNANCY})


def _install(actor):
    install_policy(actor, enabled=LIFE_TAGS)
    install_lifesim(actor)
    actor.register_handler(StartPartnershipHandler())
    actor.register_handler(StartPregnancyHandler())
    actor.register_handler(ResolveBirthHandler())
    actor.register_handler(AdoptChildHandler())
    actor.register_handler(ChooseAspirationHandler())
    actor.register_handler(CompleteMilestoneHandler())
    actor.register_handler(PracticeSkillHandler())
    actor.register_handler(StudySkillHandler())
    actor.register_handler(MentorSkillHandler())
    actor.register_handler(FindJobHandler())
    actor.register_handler(GoToWorkHandler())
    actor.register_handler(QuitJobHandler())
    actor.register_handler(PayWageHandler())
    actor.register_handler(AssessTaxHandler())
    actor.register_handler(ChargeRentHandler())
    actor.register_handler(PayBillHandler())
    actor.register_handler(OpenBusinessHandler())
    actor.register_handler(SellItemHandler())
    actor.register_handler(PromoteBusinessHandler())
    actor.register_handler(JoinHouseholdHandler())
    actor.register_handler(ClaimHomeHandler())
    actor.register_handler(ClaimRoomHandler())
    actor.register_handler(SetRoutineHandler())
    actor.register_handler(SetRelationshipStatusHandler())
    actor.register_handler(SpreadGossipHandler())
    actor.register_handler(WitnessRomanceHandler())


def _co_parent(scenario, *, boundary=None):
    components = [
        IdentityComponent(name="Hazel", kind="character"),
        CharacterComponent(species="bunny"),
        ReproductiveComponent(can_cause_pregnancy=True, species_group="bunny"),
    ]
    if boundary is not None:
        components.append(boundary)
    entity = spawn_entity(scenario.actor.world, components)
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


def _child(scenario, *, name="Clover"):
    entity = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity.id


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


def _cmd_for(scenario, character_id, command_type, **payload):
    generation = scenario.actor.current_generation(character_id, scenario.controller)
    assert generation is not None
    return build_submitted_command(
        character_id=str(character_id),
        controller_id=str(scenario.controller),
        controller_generation=generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


async def test_aspiration_milestone_completion_can_reward_inventory_item():
    scenario = build_scenario()
    _install(scenario.actor)
    completed: list[MilestoneCompletedEvent] = []
    scenario.actor.bus.subscribe(MilestoneCompletedEvent, completed.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "choose-aspiration",
            name="Cozy Homemaker",
            milestones=("meet a friend",),
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(
            scenario,
            "complete-milestone",
            milestone="meet a friend",
            reward_name="woven keepsake",
        )
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    aspiration = character.get_component(AspirationComponent)
    assert aspiration.name == "Cozy Homemaker"
    assert aspiration.completed == ("meet a friend",)
    reward_id = completed[0].reward_item_id
    assert reward_id is not None
    inventory_ids = {str(target_id) for _edge, target_id in character.get_relationships(Contains)}
    assert reward_id in inventory_ids


async def test_lifesim_aging_is_disabled_by_default():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AgeComponent(born_at_epoch=0))
    character.add_component(LifeStageComponent(stage="child"))

    await scenario.actor.tick(100 * 365 * 24 * 60 * 60)

    policies = list(
        scenario.actor.world.query().with_all([LifesimAgingPolicyComponent]).execute_entities()
    )
    assert policies[0].get_component(LifesimAgingPolicyComponent).natural_aging is False
    assert character.get_component(LifeStageComponent).stage == "child"
    assert not character.has_component(DownedComponent)
    assert not character.has_component(DeadComponent)


async def test_enabled_lifesim_aging_reuses_core_death_lifecycle():
    scenario = build_scenario()
    _install(scenario.actor)
    configure_lifesim_aging(
        scenario.actor,
        natural_aging=True,
        adult_age_seconds=10,
        elder_age_seconds=20,
        natural_death_age_seconds=30,
        natural_death_checks=1,
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AgeComponent(born_at_epoch=0))
    character.add_component(LifeStageComponent(stage="child"))
    character.add_component(HealthComponent(current=100.0, maximum=100.0))
    died: list[CharacterDiedEvent] = []
    scenario.actor.bus.subscribe(CharacterDiedEvent, died.append)

    await scenario.actor.tick(20.0)

    assert character.get_component(LifeStageComponent).stage == "elder"
    assert character.get_component(HealthComponent).current == 100.0
    assert not character.has_component(DownedComponent)

    await scenario.actor.tick(10.0)

    assert character.get_component(HealthComponent).current == 0.0
    assert character.get_component(DownedComponent).cause == "natural causes"
    assert not character.has_component(DeadComponent)
    assert died == []

    await scenario.actor.tick(1.0)

    assert character.get_component(DeadComponent).cause == "natural causes"
    assert not character.has_component(DownedComponent)
    assert died[-1].cause == "natural causes"


def test_lifesim_aging_policy_is_world_level_and_persists(tmp_path):
    scenario = build_scenario()
    _install(scenario.actor)

    configure_lifesim_aging(scenario.actor, natural_aging=True)
    path = tmp_path / "world.json"
    save_world(scenario.actor, path, meta=WorldMeta(seed="aging"))

    loaded, _meta = load_world(path)
    policies = list(loaded.world.query().with_all([LifesimAgingPolicyComponent]).execute_entities())
    assert len(policies) == 1
    assert policies[0].get_component(LifesimAgingPolicyComponent).natural_aging is True


def test_install_lifesim_can_enable_natural_aging_server_wide():
    scenario = build_scenario()

    install_lifesim(scenario.actor, natural_aging=True)

    policies = list(
        scenario.actor.world.query().with_all([LifesimAgingPolicyComponent]).execute_entities()
    )
    assert len(policies) == 1
    assert policies[0].get_component(LifesimAgingPolicyComponent).natural_aging is True


async def test_practice_and_study_progress_skill_and_emit_level_up():
    scenario = build_scenario()
    _install(scenario.actor)
    changed: list[SkillXPChangedEvent] = []
    leveled: list[SkillLeveledEvent] = []
    scenario.actor.bus.subscribe(SkillXPChangedEvent, changed.append)
    scenario.actor.bus.subscribe(SkillLeveledEvent, leveled.append)

    await scenario.actor.submit(_cmd(scenario, "practice-skill", skill="cooking", xp=60))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "study-skill", skill="cooking", xp=50))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    skills = character.get_component(SkillSetComponent)
    assert skills.levels["cooking"] == 1
    assert skills.xp["cooking"] == 10
    assert changed[-1].level == 1
    assert leveled[0].skill == "cooking"
    fragments = lifesim_fragments(scenario.actor.world, character)
    assert any("Skill cooking: level 1, 10 xp" in line for line in fragments)


async def test_mentor_skill_progresses_present_student():
    scenario = build_scenario()
    _install(scenario.actor)
    student = _co_parent(scenario)
    mentored: list[MentorshipCompletedEvent] = []
    scenario.actor.bus.subscribe(MentorshipCompletedEvent, mentored.append)

    await scenario.actor.submit(_cmd(scenario, "practice-skill", skill="gardening", xp=100))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "mentor-skill", student_id=str(student), skill="gardening", xp=95)
    )
    await scenario.actor.tick(HOUR)

    student_entity = scenario.actor.world.get_entity(student)
    skills = student_entity.get_component(SkillSetComponent)
    assert skills.levels["gardening"] == 1
    assert skills.xp["gardening"] == 0
    assert mentored[0].student_id == str(student)


async def test_career_shift_pays_funds_and_can_promote():
    scenario = build_scenario()
    _install(scenario.actor)
    shifts: list[WorkShiftCompletedEvent] = []
    promotions: list[PromotionEarnedEvent] = []
    scenario.actor.bus.subscribe(WorkShiftCompletedEvent, shifts.append)
    scenario.actor.bus.subscribe(PromotionEarnedEvent, promotions.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "find-job",
            title="Burrow Barista",
            hourly_pay=12,
            shift_duration_seconds=2 * 3600,
            shift_interval_seconds=HOUR,
            next_shift_epoch=0,
        )
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "go-to-work", performance_gain=1.0)
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    career = character.get_component(CareerComponent)
    assert career.title == "Burrow Barista"
    assert career.level == 2
    assert career.hourly_pay == 17
    assert character.get_component(HouseholdFundsComponent).balance == 24
    schedule = character.get_component(JobScheduleComponent)
    assert schedule.next_shift_epoch == scenario.actor.epoch + HOUR
    assert shifts[0].earned == 24
    assert promotions[0].level == 2


async def test_household_economy_pays_wages_taxes_rent_and_bills():
    scenario = build_scenario()
    _install(scenario.actor)
    employer = scenario.actor.world.get_entity(scenario.character)
    employer.add_component(HouseholdFundsComponent(balance=100))
    worker = spawn_entity(
        scenario.actor.world,
        [
            ActionPointsComponent(current=5.0, maximum=5.0),
            IdentityComponent(name="Marigold", kind="character"),
            CharacterComponent(),
            HouseholdFundsComponent(balance=5),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), worker.id
    )
    worker.add_relationship(ControlledBy(generation=0), scenario.controller)
    wages: list[WagePaidEvent] = []
    taxes: list[TaxAssessedEvent] = []
    paid: list[BillPaidEvent] = []
    scenario.actor.bus.subscribe(WagePaidEvent, wages.append)
    scenario.actor.bus.subscribe(TaxAssessedEvent, taxes.append)
    scenario.actor.bus.subscribe(BillPaidEvent, paid.append)

    await scenario.actor.submit(_cmd(scenario, "pay-wage", worker_id=str(worker.id), amount=25))
    await scenario.actor.tick(HOUR)

    assert employer.get_component(HouseholdFundsComponent).balance == 75
    assert worker.get_component(HouseholdFundsComponent).balance == 30
    assert wages[0].worker_balance == 30

    await scenario.actor.submit(_cmd(scenario, "assess-tax", amount=20, reason="market tax"))
    await scenario.actor.tick(HOUR)
    tax_bill_id = employer.get_relationships(HasBill)[0][1]
    assert taxes[0].bill_id == str(tax_bill_id)

    await scenario.actor.submit(_cmd(scenario, "pay-bill", bill_id=str(tax_bill_id)))
    await scenario.actor.tick(HOUR)

    assert employer.get_component(HouseholdFundsComponent).balance == 55
    assert scenario.actor.world.get_entity(tax_bill_id).get_component(
        BillComponent
    ).paid_at_epoch == scenario.actor.epoch

    await scenario.actor.submit(
        _cmd(scenario, "charge-rent", tenant_id=str(worker.id), amount=15, reason="stall rent")
    )
    await scenario.actor.tick(HOUR)
    rent_bill_id = worker.get_relationships(HasBill)[0][1]

    await scenario.actor.submit(
        _cmd_for(scenario, worker.id, "pay-bill", bill_id=str(rent_bill_id))
    )
    await scenario.actor.tick(HOUR)

    assert worker.get_component(HouseholdFundsComponent).balance == 15
    assert employer.get_component(HouseholdFundsComponent).balance == 70
    assert paid[-1].bill_id == str(rent_bill_id)
    fragments = lifesim_fragments(scenario.actor.world, worker)
    assert not any("Unpaid bills" in line for line in fragments)


async def test_business_sale_moves_item_out_of_inventory_and_pays_funds():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    item = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="berry tart", kind="item")]
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    customer = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Marigold", kind="character"),
            CharacterComponent(),
            CustomerComponent(budget=30),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), customer.id
    )
    sales: list[BusinessSaleEvent] = []
    scenario.actor.bus.subscribe(BusinessSaleEvent, sales.append)

    await scenario.actor.submit(
        _cmd(scenario, "open-business", name="Juniper's Table", default_price=10)
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "sell-item", item_id=str(item.id), customer_id=str(customer.id), price=15)
    )
    await scenario.actor.tick(HOUR)

    business_id = character.get_relationships(OwnsBusiness)[0][1]
    business = scenario.actor.world.get_entity(business_id).get_component(BusinessOwnerComponent)
    assert business.sales_count == 1
    assert character.get_component(HouseholdFundsComponent).balance == 15
    assert not character.has_relationship(Contains, item.id)
    assert customer.get_component(CustomerComponent).budget == 15
    assert sales[0].item_id == str(item.id)


async def test_household_home_and_room_claims_update_world_state():
    scenario = build_scenario()
    _install(scenario.actor)
    joined: list[HouseholdJoinedEvent] = []
    scenario.actor.bus.subscribe(HouseholdJoinedEvent, joined.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-household", household_id="burrow-1", name="Moss Burrow")
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "claim-home", room_id=str(scenario.room_a)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "claim-room", room_id=str(scenario.room_b)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    home = scenario.actor.world.get_entity(scenario.room_a).get_component(HomeComponent)
    claim = scenario.actor.world.get_entity(scenario.room_b).get_component(RoomClaimComponent)
    household = character.get_component(HouseholdComponent)
    assert household.household_id == "burrow-1"
    assert household.name == "Moss Burrow"
    assert home.owner_id == str(scenario.character)
    assert home.household_id == "burrow-1"
    assert claim.claimed_by_id == str(scenario.character)
    assert joined[0].household_name == "Moss Burrow"


async def test_routine_due_consequence_advances_next_due_without_auto_commanding():
    scenario = build_scenario()
    _install(scenario.actor)
    due: list[RoutineDueEvent] = []
    scenario.actor.bus.subscribe(RoutineDueEvent, due.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "set-routine",
            activity="water the window herbs",
            interval_seconds=HOUR,
            next_due_epoch=HOUR,
        )
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR)

    routine_id = scenario.actor.world.get_entity(scenario.character).get_relationships(
        HasRoutine
    )[0][1]
    routine = scenario.actor.world.get_entity(routine_id).get_component(RoutineComponent)
    assert routine.activity == "water the window herbs"
    assert routine.last_completed_epoch == scenario.actor.epoch
    assert routine.next_due_epoch == scenario.actor.epoch + HOUR
    assert due[0].activity == "water the window herbs"


async def test_start_partnership_creates_bidirectional_edges():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    started: list[PartnershipStartedEvent] = []
    scenario.actor.bus.subscribe(PartnershipStartedEvent, started.append)

    await scenario.actor.submit(_cmd(scenario, "start-partnership", target_id=str(target)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    partner = scenario.actor.world.get_entity(target)
    assert character.has_relationship(PartnerOf, target)
    assert partner.has_relationship(PartnerOf, scenario.character)
    assert started[0].partner_id == str(target)


async def test_relationship_status_transition_is_prompt_visible():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "set-relationship-status",
            target_id=str(target),
            status="friend",
        )
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    fragments = lifesim_fragments(scenario.actor.world, character)
    assert any("Hazel is your friend" in line for line in fragments)


async def test_gossip_changes_target_reputation_and_prompt_context():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    gossip: list[GossipSpreadEvent] = []
    scenario.actor.bus.subscribe(GossipSpreadEvent, gossip.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "spread-gossip",
            target_id=str(target),
            text="rescued a neighbor",
            reputation_delta=0.25,
        )
    )
    await scenario.actor.tick(HOUR)

    target_entity = scenario.actor.world.get_entity(target)
    reputation = target_entity.get_component(ReputationComponent)
    assert reputation.score == 0.25
    assert reputation.known_for == ("rescued a neighbor",)
    assert gossip[0].target_id == str(target)
    fragments = lifesim_fragments(scenario.actor.world, target_entity)
    assert any("rescued a neighbor" in line for line in fragments)


async def test_witnessed_romance_between_partner_and_rival_triggers_jealousy():
    scenario = build_scenario()
    _install(scenario.actor)
    partner = _co_parent(scenario)
    rival = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Poppy", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rival.id
    )
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(PartnerOf(since_epoch=0), partner)
    events: list[JealousyTriggeredEvent] = []
    scenario.actor.bus.subscribe(JealousyTriggeredEvent, events.append)

    await scenario.actor.submit(
        _cmd(
            scenario,
            "witness-romance",
            partner_id=str(partner),
            rival_id=str(rival.id),
            intensity=0.75,
        )
    )
    await scenario.actor.tick(HOUR)

    jealousy_edges = character.get_relationships(JealousOf)
    assert len(jealousy_edges) == 1
    jealousy, target_id = jealousy_edges[0]
    assert target_id == rival.id
    assert jealousy.partner_id == str(partner)
    assert jealousy.intensity == 0.75
    assert events[0].rival_id == str(rival.id)


async def test_start_pregnancy_requires_policy_consent():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    target = _co_parent(
        scenario,
        boundary=CharacterBoundaryComponent(denied=frozenset({BoundaryTag.PREGNANCY})),
    )
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(HOUR)

    assert not character.has_component(PregnancyComponent)
    assert any("consented" in r.reason for r in rejects)


async def test_pregnancy_becomes_due_while_suspended_but_birth_waits_for_resume():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    target = _co_parent(scenario)
    due: list[BirthDueEvent] = []
    scenario.actor.bus.subscribe(BirthDueEvent, due.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(0.0)
    assert character.has_component(PregnancyComponent)

    suspended_controller = spawn_entity(scenario.actor.world)
    scenario.actor.suspend(scenario.character, suspended_controller.id)
    await scenario.actor.tick(HOUR * 2)

    assert character.has_component(SuspendedComponent)
    assert character.has_component(BirthDueComponent)
    assert len(due) == 1
    children = [
        target_id for _edge, target_id in character.get_relationships(ParentOf)
    ]
    assert children == []


async def test_relationship_pregnancy_and_birth_create_llm_controlled_child():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        ReproductiveComponent(can_be_pregnant=True, species_group="bunny")
    )
    target = _co_parent(scenario)
    resolved: list[BirthResolvedEvent] = []
    scenario.actor.bus.subscribe(BirthResolvedEvent, resolved.append)

    await scenario.actor.submit(
        _cmd(scenario, "start-partnership", target_id=str(target))
    )
    await scenario.actor.tick(HOUR)
    assert character.has_relationship(PartnerOf, target)

    await scenario.actor.submit(
        _cmd(scenario, "start-pregnancy", co_parent_id=str(target), due_in_seconds=HOUR)
    )
    await scenario.actor.tick(0.0)
    await scenario.actor.tick(HOUR * 2)
    await scenario.actor.submit(_cmd(scenario, "resolve-birth", child_name="Clover"))
    await scenario.actor.tick(HOUR)

    assert not character.has_component(PregnancyComponent)
    assert not character.has_component(BirthDueComponent)
    child_id = resolved[0].child_id
    child = scenario.actor.world.get_entity(
        next(target_id for _edge, target_id in character.get_relationships(ParentOf))
    )
    assert str(child.id) == child_id
    assert child.get_component(IdentityComponent).name == "Clover"
    assert child.get_component(AgeComponent).born_at_epoch == scenario.actor.epoch
    assert child.get_component(LifeStageComponent).stage == "child"
    assert scenario.actor.world.get_entity(target).has_relationship(ParentOf, child.id)
    controllers = [
        target_id
        for _edge, target_id in child.get_relationships(ControlledBy)
    ]
    assert len(controllers) == 1
    controller = scenario.actor.world.get_entity(controllers[0])
    assert controller.has_component(LLMControllerComponent)


async def test_adopt_child_creates_parent_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    child = _child(scenario)
    adopted: list[AdoptionCompletedEvent] = []
    scenario.actor.bus.subscribe(AdoptionCompletedEvent, adopted.append)

    await scenario.actor.submit(_cmd(scenario, "adopt-child", child_id=str(child)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(ParentOf, child)
    assert adopted[0].child_id == str(child)
    assert adopted[0].parent_id == str(scenario.character)


async def test_adopt_child_rejects_non_child_target():
    scenario = build_scenario()
    _install(scenario.actor)
    target = _co_parent(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "adopt-child", child_id=str(target)))
    await scenario.actor.tick(HOUR)

    assert any(r.reason == "target is not a child" for r in rejects)


def test_lifesim_fragments_describe_partner_and_pregnancy():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    partner = _co_parent(scenario)
    child = _child(scenario)
    character.add_relationship(PartnerOf(since_epoch=0), partner)
    character.add_relationship(ParentOf(), child)
    character.add_component(
        PregnancyComponent(started_at_epoch=0, due_at_epoch=10, co_parent_ids=(str(partner),))
    )

    fragments = lifesim_fragments(scenario.actor.world, character)

    assert any("partners with Hazel" in line for line in fragments)
    assert any("pregnant" in line for line in fragments)
    assert any("Your children: Clover" in line for line in fragments)


def test_lifesim_fragments_describe_parents():
    scenario = build_scenario()
    child = _child(scenario)
    parent = scenario.actor.world.get_entity(scenario.character)
    parent.add_relationship(ParentOf(), child)

    fragments = lifesim_fragments(scenario.actor.world, scenario.actor.world.get_entity(child))

    assert any("Your parents: Juniper" in line for line in fragments)


def test_kinship_queries_return_parent_child_partner_and_sibling_labels():
    scenario = build_scenario()
    parent = scenario.actor.world.get_entity(scenario.character)
    child = _child(scenario, name="Clover")
    sibling = _child(scenario, name="Fern")
    partner = _co_parent(scenario)
    parent.add_relationship(ParentOf(), child)
    parent.add_relationship(ParentOf(), sibling)
    parent.add_relationship(PartnerOf(since_epoch=0), partner)

    assert kinship_label(scenario.actor.world, child, scenario.character) == "parent"
    assert kinship_label(scenario.actor.world, scenario.character, child) == "child"
    assert kinship_label(scenario.actor.world, scenario.character, partner) == "partner"
    assert kinship_label(scenario.actor.world, child, sibling) == "sibling"
