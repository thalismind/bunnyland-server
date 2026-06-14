"""Tests for the foundation prompt builder (spec 16)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    AffectComponent,
    AffectVector,
    ContainmentMode,
    Contains,
    DeadComponent,
    DownedComponent,
    IdentityComponent,
    MemoryProfileComponent,
    PortableComponent,
    SleepingComponent,
    SuspendedComponent,
    spawn_entity,
)
from bunnyland.mechanics.dinosim import (
    ApexPredatorComponent,
    ArmyResponseComponent,
    BoneComponent,
    ContainmentPanicComponent,
    CreatureMilkComponent,
    CreatureProductComponent,
    EggComponent,
    EnclosureComponent,
    EscapeRiskComponent,
    FenceComponent,
    FossilFragmentComponent,
    FossilSurveyComponent,
    GateComponent,
    GuardAnimalComponent,
    HideComponent,
    ImprintComponent,
    IncubationComponent,
    LabIncubationComponent,
    RanchLaborComponent,
    SettlementDamageComponent,
    SpeciesIdentificationComponent,
    ToxinComponent,
    TrainingComponent,
    WeakPointComponent,
)
from bunnyland.mechanics.dragonsim import (
    AncientBeastComponent,
    ArtifactComponent,
    EncounterZoneComponent,
    FactionComponent,
    GreatSoulComponent,
    JailComponent,
    KnowsSpell,
    LockDifficultyComponent,
    LoreBookComponent,
    MagicComponent,
    MapMarkerComponent,
    MemberOf,
    PointOfInterestComponent,
    PotionRecipeComponent,
    QuestComponent,
    QuestStageComponent,
    SpellComponent,
    SpellCooldownComponent,
    SurrenderComponent,
    VoiceInscriptionComponent,
    WantedComponent,
)
from bunnyland.mechanics.meter import Meter
from bunnyland.mechanics.needs import HungerComponent, ThirstComponent, need_fragments
from bunnyland.memory import InMemoryStore
from bunnyland.projections import RecentContextProjection, RoomSummaryProjection
from bunnyland.prompts import (
    ComponentPromptContext,
    PerspectivePhrase,
    PromptBuilder,
    PromptPerspective,
    render_prompt,
)
from bunnyland.prompts.builder import _status


def add_item(scenario, room_id, name):
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="item"), PortableComponent()],
    )
    scenario.actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )
    return item


def test_build_context_has_core_sections():
    scenario = build_scenario()
    add_item(scenario, scenario.room_a, "three berries")
    builder = PromptBuilder(scenario.actor.world)

    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)

    assert ctx.name == "Juniper"
    assert ctx.status.startswith("active")
    assert ctx.action == (5.0, 5.0)
    assert ctx.location_title == "Mosslit Burrow"
    assert "three berries" in ctx.visible_objects
    assert "north" in ctx.exits
    assert "move north" in ctx.commands
    assert "take note" in ctx.commands


def test_status_helper_uses_condition_precedence(scenario):
    character = scenario.actor.world.get_entity(scenario.character)

    assert _status(character) == "active"

    character.add_component(SleepingComponent())
    assert _status(character) == "asleep"

    character.add_component(DownedComponent(downed_at_epoch=0, cause="test"))
    assert _status(character) == "downed"

    character.add_component(SuspendedComponent())
    assert _status(character) == "suspended"

    character.add_component(DeadComponent(died_at_epoch=0, cause="test"))
    assert _status(character) == "dead"


def test_build_context_includes_needs_feelings_and_notes():
    scenario = build_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(HungerComponent(meter=Meter(value=75.0)))  # urgent
    char.add_component(ThirstComponent(meter=Meter(value=10.0)))  # calm -> no phrase
    char.add_component(
        AffectComponent(current=AffectVector(stress=20.0), labels=frozenset({"tense"}))
    )
    char.add_component(MemoryProfileComponent(vector_collection="juniper"))

    store = InMemoryStore()
    store.add("juniper", text="The basin water is unsafe.", created_at_epoch=1)

    builder = PromptBuilder(
        scenario.actor.world,
        memory_store=store,
        fragment_providers=[need_fragments],
    )
    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)

    assert any("hungry" in n for n in ctx.conditions)
    assert all("dry" not in n for n in ctx.conditions)  # thirst calm
    assert "tense" in ctx.feelings
    assert "The basin water is unsafe." in ctx.notes


def test_component_prompt_context_lazy_room_siblings_and_inventory_helpers():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    room = world.get_entity(scenario.room_a)
    nearby = add_item(scenario, scenario.room_a, "nearby berries")
    carried = spawn_entity(
        world,
        [IdentityComponent(name="carried berries", kind="item"), PortableComponent()],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), carried.id)
    ctx = ComponentPromptContext.for_entity(world, character)
    target_ctx = ComponentPromptContext.for_entity(
        world,
        nearby,
        perspective=ctx.perspective,
        target=character,
    )
    observer_ctx = ComponentPromptContext.for_entity(
        world,
        nearby,
        perspective=PromptPerspective(viewer=room),
        target=character,
    )

    assert ctx.room == room
    assert ctx.can_view_private_state is True
    assert target_ctx.can_view_private_state is True
    assert observer_ctx.can_view_private_state is False
    assert ctx.room_siblings(PortableComponent) == (nearby,)
    assert ctx.inventory_items(PortableComponent) == (carried,)

    later_nearby = add_item(scenario, scenario.room_a, "later berries")
    later_carried = spawn_entity(
        world,
        [IdentityComponent(name="later carried berries", kind="item"), PortableComponent()],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), later_carried.id)

    assert ctx.room_siblings(PortableComponent) == (nearby,)
    assert ctx.inventory_items(PortableComponent) == (carried,)
    fresh_ctx = ComponentPromptContext.for_entity(world, character)
    assert fresh_ctx.room_siblings(PortableComponent) == (nearby, later_nearby)
    assert fresh_ctx.inventory_items(PortableComponent) == (carried, later_carried)


def test_perspective_phrase_supports_static_and_templated_lines():
    phrase = PerspectivePhrase(
        "I have {count} berry.",
        "You have {count} berry.",
        "They have {count} berry.",
    )

    assert phrase.render("first-person", count=1) == "I have 1 berry."
    assert phrase.render("second-person", count=1) == "You have 1 berry."
    assert PerspectivePhrase("Ready.", "Ready.", "Ready.").render("third-person") == "Ready."


def test_migrated_component_prompt_fragments_cover_cross_pack_branches():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    def entity(name, *components):
        return spawn_entity(world, [IdentityComponent(name=name, kind="thing"), *components])

    def target_ctx(item):
        return ComponentPromptContext.for_entity(
            world, item, perspective=self_ctx.perspective, target=character
        )

    def observer_target_ctx(item):
        return ComponentPromptContext.for_entity(
            world, item, perspective=other_ctx.perspective, target=character
        )

    self_ctx = ComponentPromptContext.for_entity(world, character)
    other = entity("viewer")
    other_ctx = ComponentPromptContext.for_entity(
        world, character, perspective=PromptPerspective(viewer=other)
    )

    discovered = entity("ruin", PointOfInterestComponent(discovered=True))
    marker = entity(
        "camp", MapMarkerComponent(label="Camp", marked_by=(str(character.id),))
    )
    inactive_zone = entity("zone", EncounterZoneComponent(active=False))
    active_quest = entity(
        "quest",
        QuestComponent(
            quest_id="q1",
            title="Find the relic",
            status="active",
            accepted_by=(str(character.id),),
        ),
    )
    declined_quest = entity(
        "declined", QuestComponent(quest_id="q2", title="Bad idea", status="declined")
    )
    stage = entity(
        "stage",
        QuestStageComponent(quest_id="q1", stage=2, tracked_by=(str(character.id),), branch="a"),
    )
    faction = entity("Companions", FactionComponent(name="Companions"))
    known_spell = entity("spark", SpellComponent(name="Spark"))
    character.add_relationship(KnowsSpell(), known_spell.id)

    assert discovered.get_component(PointOfInterestComponent).prompt_fragments(
        target_ctx(discovered)
    ) == ()
    assert marker.get_component(MapMarkerComponent).prompt_fragments(target_ctx(marker)) == (
        "Map marker: Camp (landmark).",
    )
    assert marker.get_component(MapMarkerComponent).prompt_fragments(
        observer_target_ctx(marker)
    ) == ()
    assert MapMarkerComponent(label="Hidden").prompt_fragments(self_ctx) == ()
    assert inactive_zone.get_component(EncounterZoneComponent).prompt_fragments(
        target_ctx(inactive_zone)
    ) == ()
    assert EncounterZoneComponent(zone_type="crypt", danger_rating=3).prompt_fragments(
        self_ctx
    ) == ("Encounter zone nearby: crypt (danger 3).",)
    assert active_quest.get_component(QuestComponent).prompt_fragments(
        target_ctx(active_quest)
    ) == ("Active quest: Find the relic.",)
    assert active_quest.get_component(QuestComponent).prompt_fragments(
        observer_target_ctx(active_quest)
    ) == ()
    assert declined_quest.get_component(QuestComponent).prompt_fragments(
        target_ctx(declined_quest)
    ) == ("Declined quest: Bad idea.",)
    assert QuestComponent(quest_id="q3", title="Ignored").prompt_fragments(self_ctx) == ()
    assert stage.get_component(QuestStageComponent).prompt_fragments(target_ctx(stage)) == (
        "Tracked quest stage 2 for q1, branch a.",
    )
    assert stage.get_component(QuestStageComponent).prompt_fragments(
        observer_target_ctx(stage)
    ) == ()
    assert QuestStageComponent(quest_id="q1").prompt_fragments(self_ctx) == ()
    assert JailComponent(faction_id="hold", release_epoch=10).prompt_fragments(other_ctx) == ()
    assert JailComponent(faction_id="hold", release_epoch=10).prompt_fragments(self_ctx) == (
        "Serving jail time for hold until 10.",
    )
    assert MemberOf(rank="thane").prompt_fragments(self_ctx) == ()
    assert MemberOf(rank="thane").prompt_fragments(
        ComponentPromptContext.for_entity(world, character, target=faction)
    ) == ("You are a thane of Companions.",)
    assert MemberOf(rank="thane").prompt_fragments(
        ComponentPromptContext.for_entity(
            world, character, perspective=other_ctx.perspective, target=faction
        )
    ) == ()
    assert AncientBeastComponent(name="Alduin", soul_absorbed=True).prompt_fragments(
        self_ctx
    ) == ("Ancient beast nearby: Alduin (soul absorbed).",)
    assert GreatSoulComponent(souls=0).prompt_fragments(self_ctx) == ()
    assert WantedComponent(amounts={"hold": 40}).prompt_fragments(other_ctx) == ()
    assert WantedComponent(amounts={"hold": 40}).prompt_fragments(self_ctx) == (
        "Bounty of 40 with hold.",
    )
    assert LockDifficultyComponent(locked=False).prompt_fragments(self_ctx) == ()
    assert LockDifficultyComponent(difficulty=5).prompt_fragments(
        ComponentPromptContext.for_entity(world, entity("chest"))
    ) == ("Locked target nearby: chest (difficulty 5).",)
    assert LoreBookComponent(title="Read", read_by=(str(character.id),)).prompt_fragments(
        target_ctx(known_spell)
    ) == ()
    assert LoreBookComponent(title="Herbs", skill_name="alchemy").prompt_fragments(
        self_ctx
    ) == ("Unread skill book nearby: Herbs (alchemy).",)
    assert MagicComponent().prompt_fragments(other_ctx) == ()
    assert SpellCooldownComponent().prompt_fragments(self_ctx) == ()
    assert SpellCooldownComponent(ready_at_epoch=7).prompt_fragments(self_ctx) == (
        "Spell cooldown nearby: ready at epoch 7.",
    )
    assert SurrenderComponent().prompt_fragments(other_ctx) == ()
    assert known_spell.get_component(SpellComponent).prompt_fragments(
        target_ctx(known_spell)
    ) == ("Spell learned: Spark.",)
    assert known_spell.get_component(SpellComponent).prompt_fragments(
        observer_target_ctx(known_spell)
    ) == ()
    unknown_spell = entity("bolt", SpellComponent(name="Bolt"))
    assert unknown_spell.get_component(SpellComponent).prompt_fragments(
        target_ctx(unknown_spell)
    ) == ("Learnable spell nearby: Bolt.",)
    assert PotionRecipeComponent(name="Health", potion_name="Health").prompt_fragments(
        self_ctx
    ) == ("Potion recipe nearby: Health.",)
    assert ArtifactComponent(name="Blade", identified_by=(str(character.id),)).prompt_fragments(
        target_ctx(known_spell)
    ) == ("Artifact nearby: Blade (1 charges, identified).",)
    assert VoiceInscriptionComponent(word_id="w", studied_by=(str(character.id),)).prompt_fragments(
        target_ctx(known_spell)
    ) == ()
    assert VoiceInscriptionComponent(word_id="w").prompt_fragments(target_ctx(known_spell)) == (
        "Voice inscription nearby: spark.",
    )

    fossil = entity("fossil", FossilFragmentComponent())
    fossil.add_component(SpeciesIdentificationComponent(species_name="raptor"))
    egg = entity(
        "egg",
        EggComponent(species_name="raptor", laid_at_epoch=0),
        IncubationComponent(started_at_epoch=0, ready=True, temperature=37.0),
    )
    enclosure = entity(
        "pen",
        EnclosureComponent(name="Raptor pen"),
        ContainmentPanicComponent(),
        FenceComponent(),
        GateComponent(open=True, locked=True),
        EscapeRiskComponent(risk=2.0),
    )

    assert fossil.get_component(FossilFragmentComponent).prompt_fragments(
        target_ctx(fossil)
    ) == ("Nearby fossil: fossil (raptor).",)
    assert FossilSurveyComponent(stabilized=True).prompt_fragments(target_ctx(fossil)) == (
        "Fossil survey fossil: stabilized.",
    )
    assert egg.get_component(EggComponent).prompt_fragments(target_ctx(egg)) == (
        "Nearby egg: egg (raptor, ready to hatch, 37 C).",
    )
    assert LabIncubationComponent(lab_id="lab", active=False).prompt_fragments(
        target_ctx(egg)
    ) == ()
    assert ContainmentPanicComponent(active=False).prompt_fragments(
        target_ctx(enclosure)
    ) == ()
    assert TrainingComponent().prompt_fragments(target_ctx(enclosure)) == ()
    assert ImprintComponent(imprinted_by="other").prompt_fragments(target_ctx(egg)) == ()
    assert enclosure.get_component(ContainmentPanicComponent).prompt_fragments(
        target_ctx(enclosure)
    ) == ("Raptor pen containment panic: severity 1.",)
    assert enclosure.get_component(FenceComponent).prompt_fragments(target_ctx(enclosure)) == (
        "Raptor pen fence: 10/10.",
    )
    assert enclosure.get_component(GateComponent).prompt_fragments(target_ctx(enclosure)) == (
        "Raptor pen gate: open, locked.",
    )
    assert FenceComponent().prompt_fragments(self_ctx) == ()
    assert GateComponent().prompt_fragments(self_ctx) == ()
    assert enclosure.get_component(EscapeRiskComponent).prompt_fragments(
        target_ctx(enclosure)
    ) == ("Raptor pen escape risk: 2.",)
    assert SettlementDamageComponent(repaired=True).prompt_fragments(target_ctx(enclosure)) == ()
    assert WeakPointComponent(exposed=False).prompt_fragments(target_ctx(enclosure)) == ()
    assert ApexPredatorComponent(threat_level=0).prompt_fragments(target_ctx(enclosure)) == ()
    assert ArmyResponseComponent(called=False).prompt_fragments(target_ctx(enclosure)) == ()
    assert CreatureProductComponent(product_type="egg", quantity=0).prompt_fragments(
        target_ctx(enclosure)
    ) == ()
    assert HideComponent(harvested=True).prompt_fragments(target_ctx(enclosure)) == ()
    assert BoneComponent(harvested=True).prompt_fragments(target_ctx(enclosure)) == ()
    assert ToxinComponent(quantity=0).prompt_fragments(target_ctx(enclosure)) == ()
    assert CreatureMilkComponent(volume=0).prompt_fragments(target_ctx(enclosure)) == ()
    assert RanchLaborComponent(active=False).prompt_fragments(target_ctx(enclosure)) == ()
    assert GuardAnimalComponent(active=False).prompt_fragments(target_ctx(enclosure)) == ()


def test_render_prompt_matches_foundation_layout():
    scenario = build_scenario()
    builder = PromptBuilder(scenario.actor.world)
    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)
    text = render_prompt(ctx)

    assert "You are Juniper, a character." in text
    assert "Location:" in text
    assert "Points:" in text
    assert "Action: 5.0/5.0" in text
    assert "Available commands:" in text


def test_recent_context_appears_in_prompt():
    scenario = build_scenario()
    recent = RecentContextProjection(scenario.actor.world)
    # seed a recent entry directly
    recent._log[str(scenario.room_a)].append("Hazel warned the water tasted strange.")
    builder = PromptBuilder(
        scenario.actor.world,
        room_summary=RoomSummaryProjection(scenario.actor.world),
        recent_context=recent,
    )
    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)
    assert "Hazel warned the water tasted strange." in ctx.recent
    assert "Recent context:" in render_prompt(ctx)
