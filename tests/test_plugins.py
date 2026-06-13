"""Tests for the plugin system: loading, dependency ordering, and application."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest
from conftest import build_scenario, install_plugin_module

from bunnyland.core import (
    DEFAULT_ACTION_DEFINITIONS,
    ActionArgument,
    ActionDefinition,
    ActionExample,
    ActionPattern,
    AdminComponent,
    CommandCost,
    Contains,
    ControllerOutboxMessageComponent,
    DiscordControllerComponent,
    HandlerContext,
    HandlerResult,
    Lane,
    MemoryProfileComponent,
    SubmittedCommand,
    WorldActor,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import NoteTakenEvent
from bunnyland.core.handlers import ok
from bunnyland.llm_agents.tools import tool_schemas
from bunnyland.mechanics.storyteller import IncidentSpawned
from bunnyland.plugins import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginError,
    apply_plugins,
    bunnyland_plugins,
    load_and_apply,
    load_modules,
    resolve_order,
    select,
)
from bunnyland.plugins.builtin import (
    BARBARIANSIM,
    COLONYSIM,
    CORE_VERBS,
    DAGGERSIM,
    DINOSIM,
    DRAGONSIM,
    ENVIRONMENT,
    GARDENSIM,
    LIFESIM,
    MCP,
    MECHANISMS,
    MEMORY,
    NEONSIM,
    NUKESIM,
    PERSONA,
    POLICY,
    SOCIAL,
    STORYTELLER,
    TOONSIM,
    VOIDSIM,
    WORLDGEN,
    core_verbs_plugin,
    storyteller_plugin,
)
from bunnyland.plugins.contributions import collect_content_items, collect_ecs_types


def test_builtin_plugins_declared():
    ids = {p.id for p in bunnyland_plugins()}
    assert ids == {
        BARBARIANSIM,
        COLONYSIM,
        CORE_VERBS,
        LIFESIM,
        MEMORY,
        WORLDGEN,
        ENVIRONMENT,
        MECHANISMS,
        SOCIAL,
        POLICY,
        PERSONA,
        GARDENSIM,
        DRAGONSIM,
        DAGGERSIM,
        DINOSIM,
        MCP,
        VOIDSIM,
        NUKESIM,
        NEONSIM,
        TOONSIM,
        STORYTELLER,
    }


def test_select_defaults_to_default_enabled():
    plugins = bunnyland_plugins()
    assert len(select(plugins, None)) == 20
    assert [p.id for p in select(plugins, [MEMORY])] == [MEMORY]


def test_collect_prompt_fragments_gathers_providers():
    from bunnyland.plugins import collect_prompt_fragments

    providers = collect_prompt_fragments(bunnyland_plugins())
    # needs, environment, and social each contribute one.
    assert len(providers) >= 3
    assert all(callable(p) for p in providers)


def test_collect_content_items_preserves_plugin_order():
    first = object()
    second = object()
    plugins = [
        Plugin(
            id="one",
            name="One",
            content=ContentContribution(prompt_fragments=(first,)),
        ),
        Plugin(
            id="two",
            name="Two",
            content=ContentContribution(prompt_fragments=(second,)),
        ),
    ]

    assert collect_content_items(plugins, "prompt_fragments") == (first, second)
    assert collect_content_items([], "prompt_fragments") == ()


def test_collect_ecs_types_preserves_plugin_order():
    plugins = [
        Plugin(
            id="one",
            name="One",
            ecs=EcsContribution(components=(MemoryProfileComponent,), edges=(Contains,)),
        )
    ]

    assert collect_ecs_types(plugins) == ((MemoryProfileComponent,), (Contains,))
    assert collect_ecs_types([]) == ((), ())


def test_builtin_admin_and_storyteller_ecs_types_are_registered():
    assert AdminComponent in core_verbs_plugin().ecs.components
    assert IncidentSpawned in storyteller_plugin().ecs.edges


def test_worldgen_plugin_contributes_named_generators():
    from bunnyland.worldgen import collect_generators

    registry = collect_generators(bunnyland_plugins())
    assert {
        "empty",
        "waiting-room",
        "halloween",
        "holiday",
        "tower-debate",
        "clue-snack-demo",
        "dive-scheme-demo",
        "star-opera-demo",
        "gothic-count-demo",
        "oneshot",
        "recursive",
    } <= set(registry)
    # generators are selected by name and disappear if their plugin is dropped
    without = collect_generators([p for p in bunnyland_plugins() if p.id != WORLDGEN])
    assert "empty" not in without
    assert "waiting-room" not in without
    assert "halloween" not in without
    assert "holiday" not in without
    assert "tower-debate" not in without
    assert "clue-snack-demo" not in without
    assert "dive-scheme-demo" not in without
    assert "star-opera-demo" not in without
    assert "gothic-count-demo" not in without
    assert "oneshot" not in without
    assert "recursive" not in without
    # each sim plugin also contributes its own example world, tied to that plugin
    assert "voidsim-demo" in registry
    assert "nukesim-demo" in registry
    assert "dinosim-demo" in registry
    assert registry["empty"].uses_seed is False
    assert registry["waiting-room"].uses_seed is False
    assert registry["halloween"].uses_seed is False
    assert registry["holiday"].uses_seed is False
    assert registry["tower-debate"].uses_seed is False
    assert registry["clue-snack-demo"].uses_seed is False
    assert registry["dive-scheme-demo"].uses_seed is False
    assert registry["star-opera-demo"].uses_seed is False
    assert registry["gothic-count-demo"].uses_seed is False
    assert registry["recursive"].uses_seed is True
    assert registry["voidsim-demo"].uses_seed is False
    assert registry["nukesim-demo"].uses_seed is False
    assert registry["dinosim-demo"].uses_seed is False
    without_void = collect_generators([p for p in bunnyland_plugins() if p.id != VOIDSIM])
    assert "voidsim-demo" not in without_void
    without_nuke = collect_generators([p for p in bunnyland_plugins() if p.id != NUKESIM])
    assert "nukesim-demo" not in without_nuke
    without_dino = collect_generators([p for p in bunnyland_plugins() if p.id != DINOSIM])
    assert "dinosim-demo" not in without_dino


def test_select_unknown_id_raises():
    with pytest.raises(PluginError):
        select(bunnyland_plugins(), ["nope"])


def test_resolve_order_places_dependencies_first():
    ordered = resolve_order(bunnyland_plugins())
    ids = [p.id for p in ordered]
    assert ids.index(CORE_VERBS) < ids.index(LIFESIM)
    assert ids.index(LIFESIM) < ids.index(COLONYSIM)
    assert ids.index(COLONYSIM) < ids.index(GARDENSIM)
    assert ids.index(CORE_VERBS) < ids.index(BARBARIANSIM)
    assert ids.index(LIFESIM) < ids.index(DRAGONSIM)
    assert ids.index(BARBARIANSIM) < ids.index(VOIDSIM)
    assert ids.index(VOIDSIM) < ids.index(NUKESIM)
    assert ids.index(LIFESIM) < ids.index(DINOSIM)
    assert ids.index(COLONYSIM) < ids.index(DINOSIM)
    assert ids.index(CORE_VERBS) < ids.index(MEMORY)


def test_builtin_sim_dependencies_match_layering_contracts():
    plugins = {plugin.id: plugin for plugin in bunnyland_plugins()}

    assert plugins[LIFESIM].dependencies.requires == (CORE_VERBS,)
    assert plugins[COLONYSIM].dependencies.requires == (CORE_VERBS, LIFESIM)
    assert plugins[GARDENSIM].dependencies.requires == (
        CORE_VERBS,
        LIFESIM,
        COLONYSIM,
    )
    assert plugins[BARBARIANSIM].dependencies.requires == (CORE_VERBS,)
    assert plugins[DRAGONSIM].dependencies.requires == (CORE_VERBS, LIFESIM)
    assert plugins[DAGGERSIM].dependencies.requires == (CORE_VERBS,)
    assert plugins[VOIDSIM].dependencies.requires == (
        CORE_VERBS,
        COLONYSIM,
        BARBARIANSIM,
    )
    assert plugins[NUKESIM].dependencies.requires == (
        CORE_VERBS,
        COLONYSIM,
        BARBARIANSIM,
    )
    assert plugins[DINOSIM].dependencies.requires == (CORE_VERBS, LIFESIM, COLONYSIM)


def test_selecting_later_sim_without_required_layers_fails_clearly():
    with pytest.raises(PluginError, match="depends on missing"):
        resolve_order([select(bunnyland_plugins(), [NUKESIM])[0]])


def test_missing_dependency_raises():
    orphan = Plugin(
        id="x",
        name="X",
        dependencies=DependencyContribution(requires=("does.not.exist",)),
    )
    with pytest.raises(PluginError):
        resolve_order([orphan])


def test_dependency_cycle_raises():
    a = Plugin(id="a", name="A", dependencies=DependencyContribution(requires=("b",)))
    b = Plugin(id="b", name="B", dependencies=DependencyContribution(requires=("a",)))
    with pytest.raises(PluginError):
        resolve_order([a, b])


def test_three_plugin_dependency_cycle_raises():
    a = Plugin(id="a", name="A", dependencies=DependencyContribution(requires=("b",)))
    b = Plugin(id="b", name="B", dependencies=DependencyContribution(requires=("c",)))
    c = Plugin(id="c", name="C", dependencies=DependencyContribution(requires=("a",)))
    with pytest.raises(PluginError, match="dependency cycle"):
        resolve_order([a, b, c])


def test_missing_recommendation_warns_but_continues(caplog):
    plugin = Plugin(
        id="a",
        name="A",
        dependencies=DependencyContribution(recommends=("missing",)),
    )

    assert resolve_order([plugin]) == [plugin]
    assert "recommends missing" in caplog.text


class _WaveHandler:
    command_type = "wave"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        del ctx, command
        return ok()


def test_plugin_action_definitions_register_with_actor_and_tool_schema():
    definition = ActionDefinition(
        command_type="wave",
        tool_name="wave",
        title="Wave",
        description="Wave to a reachable character.",
        arguments={
            "target_id": ActionArgument(
                title="Target",
                description="The character to wave at.",
                kind="entity",
                required=True,
            )
        },
        examples=(ActionExample("wave to Hazel", natural=True),),
        natural_patterns=(ActionPattern("wave to {target_id}"),),
    )
    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="wave",
                name="Wave",
                commands=CommandContribution(
                    action_handlers=(_WaveHandler,),
                    action_definitions=(definition,),
                ),
            )
        ],
        actor,
    )

    assert actor.action_definitions() == (definition,)
    schema = next(
        item["function"]
        for item in tool_schemas(actor.action_definitions())
        if item["function"]["name"] == "wave"
    )
    assert schema["description"] == "Wave to a reachable character."
    assert schema["parameters"]["properties"]["target_id"]["description"] == (
        "The character to wave at."
    )


def test_plugin_handlers_get_inferred_action_definitions_when_missing():
    actor = WorldActor()
    apply_plugins(
        [
            Plugin(
                id="wave",
                name="Wave",
                commands=CommandContribution(action_handlers=(_WaveHandler,)),
            )
        ],
        actor,
    )

    definitions = actor.action_definitions()
    assert len(definitions) == 1
    assert definitions[0].command_type == "wave"
    assert definitions[0].name == "wave"


def test_builtin_handler_command_types_are_in_the_shared_action_catalog():
    catalog = {definition.command_type for definition in DEFAULT_ACTION_DEFINITIONS}
    handler_types = {
        handler.command_type
        for plugin in bunnyland_plugins()
        for handler in plugin.commands.action_handlers
    }

    assert handler_types - catalog == set()


def test_imported_plugin_ids_are_namespaced_and_selectable_by_short_id(monkeypatch):
    install_plugin_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])

    plugins = load_modules(["module_foo"])

    assert [p.id for p in plugins] == ["module_foo.bar"]
    assert [p.id for p in select(plugins, ["bar"])] == ["module_foo.bar"]


def test_imported_plugin_dependencies_are_namespaced(monkeypatch):
    install_plugin_module(
        monkeypatch,
        "module_foo",
        [
            Plugin(id="base", name="Base"),
            Plugin(
                id="bar",
                name="Bar",
                dependencies=DependencyContribution(requires=("base",), recommends=("extra",)),
            ),
        ],
    )

    plugins = load_modules(["module_foo"])
    bar = next(plugin for plugin in plugins if plugin.id == "module_foo.bar")

    assert bar.dependencies.requires == ("module_foo.base",)
    assert bar.dependencies.recommends == ("module_foo.extra",)


def test_load_modules_requires_entrypoint(monkeypatch):
    module = ModuleType("module_empty")
    monkeypatch.setitem(sys.modules, "module_empty", module)

    with pytest.raises(PluginError, match="has no bunnyland_plugins"):
        load_modules(["module_empty"])


def test_short_plugin_id_must_not_be_ambiguous(monkeypatch):
    install_plugin_module(monkeypatch, "module_one", [Plugin(id="bar", name="Bar One")])
    install_plugin_module(monkeypatch, "module_two", [Plugin(id="bar", name="Bar Two")])

    plugins = load_modules(["module_one", "module_two"])

    with pytest.raises(PluginError, match="ambiguous plugin id"):
        select(plugins, ["bar"])


def test_load_and_apply_imports_selects_and_applies_plugin(monkeypatch):
    install_plugin_module(
        monkeypatch,
        "module_wave",
        [
            Plugin(
                id="wave",
                name="Wave",
                commands=CommandContribution(action_handlers=(_WaveHandler,)),
            )
        ],
    )
    actor = WorldActor()

    applied = load_and_apply(actor, modules=["module_wave"], enabled_ids=["wave"])

    assert [plugin.id for plugin in applied] == ["module_wave.wave"]
    assert actor.action_definitions()[0].command_type == "wave"


async def test_applying_core_verbs_enables_move():
    # An actor with no plugins cannot move; applying core_verbs registers the handler.
    scenario = _bare_scenario()
    apply_plugins([p for p in bunnyland_plugins() if p.id == CORE_VERBS], scenario.actor)

    await scenario.actor.submit(_move(scenario))
    await scenario.actor.tick(3600.0)
    assert scenario.character_room() == scenario.room_b


async def test_applying_memory_plugin_enables_notes():
    scenario = _bare_scenario()
    apply_plugins([p for p in bunnyland_plugins() if p.id in (CORE_VERBS, MEMORY)], scenario.actor)
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(MemoryProfileComponent(vector_collection="c"))

    notes = []
    scenario.actor.bus.subscribe(NoteTakenEvent, notes.append)
    note = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"text": "a private thought"},
    )
    await scenario.actor.submit(note)
    await scenario.actor.tick(0.0)
    assert len(notes) == 1


async def test_applying_lifesim_plugin_enables_skill_progression():
    scenario = _bare_scenario()
    apply_plugins(
        [p for p in bunnyland_plugins() if p.id in (CORE_VERBS, LIFESIM)],
        scenario.actor,
    )
    from bunnyland.mechanics.lifesim import SkillSetComponent

    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="practice-skill",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"skill": "cooking", "xp": 100},
    )
    await scenario.actor.submit(command)
    await scenario.actor.tick(3600.0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(SkillSetComponent).levels["cooking"] == 1


async def test_disabled_plugin_leaves_its_verbs_unhandled():
    # Without the memory plugin, take-note has no handler and is rejected.
    scenario = _bare_scenario()
    apply_plugins([p for p in bunnyland_plugins() if p.id == CORE_VERBS], scenario.actor)
    from bunnyland.core import OnInsufficientPoints
    from bunnyland.core.events import CommandRejectedEvent

    rejects = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    note = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        on_insufficient_points=OnInsufficientPoints.DENY,
        payload={"text": "x"},
    )
    await scenario.actor.submit(note)
    await scenario.actor.tick(0.0)
    assert any("no handler for take-note" in r.reason for r in rejects)


def test_catalogue_parity_plugins_register_new_public_surfaces():
    plugins = {plugin.id: plugin for plugin in bunnyland_plugins()}

    core = plugins[CORE_VERBS]
    assert {"HoldableComponent", "WearableComponent"} <= {
        component.__name__ for component in core.ecs.components
    }
    assert {
        "look",
        "inspect",
        "drop",
        "open",
        "close",
        "lock",
        "unlock",
        "hold",
        "unhold",
        "wear",
        "remove",
    } <= {handler.command_type for handler in core.commands.action_handlers}
    assert {
        "RoomLookedEvent",
        "EntityInspectedEvent",
        "ContainerOpenedEvent",
        "ContainerClosedEvent",
        "DoorOpenedEvent",
        "DoorClosedEvent",
        "EntityLockedEvent",
        "EntityUnlockedEvent",
        "ItemHeldEvent",
        "ItemUnheldEvent",
        "ItemWornEvent",
        "ItemRemovedEvent",
    } <= {event.__name__ for event in core.commands.typed_events}

    lifesim = plugins[LIFESIM]
    assert {
        "CharacterProfileComponent",
        "WhimComponent",
        "HomeObjectComponent",
    } <= {component.__name__ for component in lifesim.ecs.components}
    assert "HasWhim" in {edge.__name__ for edge in lifesim.ecs.edges}
    assert {
        "update-profile",
        "add-whim",
        "complete-whim",
        "use-home-object",
        "maintain-home-object",
        "invite-over",
        "configure-aging",
    } <= {handler.command_type for handler in lifesim.commands.action_handlers}
    assert {
        "ProfileUpdatedEvent",
        "WhimAddedEvent",
        "HomeObjectMaintainedEvent",
        "LifesimAgingPolicyChangedEvent",
    } <= {event.__name__ for event in lifesim.commands.typed_events}

    colony = plugins[COLONYSIM]
    assert {
        "PawnProfileComponent",
        "JobBillComponent",
        "PrisonerComponent",
        "ResearchProjectComponent",
        "ColonyIncidentComponent",
        "TradeOfferComponent",
        "SurgeryBillComponent",
    } <= {component.__name__ for component in colony.ecs.components}
    assert "HasBodyPart" in {edge.__name__ for edge in colony.ecs.edges}
    assert {
        "update-pawn-profile",
        "progress-job-bill",
        "set-prisoner-policy",
        "recruit-prisoner",
        "research-project",
        "resolve-colony-incident",
        "complete-trade",
        "perform-surgery",
    } <= {handler.command_type for handler in colony.commands.action_handlers}
    assert {
        "PawnProfileUpdatedEvent",
        "JobBillProgressedEvent",
        "RecruitmentProgressedEvent",
        "TechUnlockedEvent",
        "ColonyIncidentResolvedEvent",
        "SurgeryPerformedEvent",
    } <= {event.__name__ for event in colony.commands.typed_events}

    garden = plugins[GARDENSIM]
    assert {
        "CropQualityComponent",
        "RegrowableComponent",
        "PestComponent",
        "MachineBreakdownComponent",
        "AnimalBreedingComponent",
        "GeodeComponent",
        "ShippingBinComponent",
        "CollectionComponent",
    } <= {component.__name__ for component in garden.ecs.components}
    assert {
        "inspect-crop",
        "weed-crop",
        "treat-pests",
        "cancel-machine",
        "repair-machine",
        "breed-animal",
        "open-geode",
        "ship-items",
        "claim-reward",
    } <= {handler.command_type for handler in garden.commands.action_handlers}
    assert {
        "CropInspectedEvent",
        "MachineProcessingCancelledEvent",
        "AnimalBornEvent",
        "GeodeOpenedEvent",
        "ItemsShippedEvent",
        "CollectionUpdatedEvent",
    } <= {event.__name__ for event in garden.commands.typed_events}

    barbarian = plugins[BARBARIANSIM]
    assert {
        "BaseClaimComponent",
        "TrapComponent",
        "SurvivalGapComponent",
        "BuildingComponent",
        "PurgeWaveComponent",
        "RitualComponent",
        "DangerZoneComponent",
        "BossComponent",
        "TreasureComponent",
        "ClimbingGateComponent",
    } <= {
        component.__name__ for component in barbarian.ecs.components
    }
    assert {
        "claim-base",
        "place-trap",
        "disarm-trap",
        "bridge-survival-gap",
        "decay-building",
        "upgrade-building",
        "demolish-building",
        "prepare-siege",
        "start-purge-wave",
        "perform-ritual",
        "explore-danger-zone",
        "defeat-boss",
        "unlock-treasure",
        "claim-treasure",
        "climb",
    } <= {
        handler.command_type for handler in barbarian.commands.action_handlers
    }
    assert {
        "BaseClaimedEvent",
        "TrapPlacedEvent",
        "TrapDisarmedEvent",
        "SurvivalGapBridgedEvent",
        "BuildingUpgradedEvent",
        "BuildingDecayedEvent",
        "BuildingDemolishedEvent",
        "PurgeWaveStartedEvent",
        "RitualPerformedEvent",
        "DangerZoneExploredEvent",
        "BossDefeatedEvent",
        "TreasureUnlockedEvent",
        "TreasureClaimedEvent",
        "ClimbingGatePassedEvent",
    } <= {
        event.__name__ for event in barbarian.commands.typed_events
    }

    dragon = plugins[DRAGONSIM]
    assert {
        "MapMarkerComponent",
        "EncounterZoneComponent",
        "PerkComponent",
        "AncientBeastComponent",
        "WordOfPowerComponent",
        "VoiceInscriptionComponent",
        "CarvableComponent",
        "LoreBookComponent",
        "LockDifficultyComponent",
        "MagickaComponent",
        "SpellComponent",
        "PotionRecipeComponent",
        "ArtifactComponent",
        "SpellCooldownComponent",
        "PersuasionComponent",
        "SurrenderComponent",
    } <= {component.__name__ for component in dragon.ecs.components}
    assert {"HasPerk", "KnowsWord", "KnowsSpell"} <= {edge.__name__ for edge in dragon.ecs.edges}
    assert {
        "mark-map",
        "trigger-encounter",
        "unlock-perk",
        "absorb-great-soul",
        "learn-word-of-power",
        "speak-word-of-power",
        "inscribe-voice-phrase",
        "study-voice-inscription",
        "change-faction-rank",
        "bribe-guard",
        "serve-jail-time",
        "pick-lock",
        "read-lore-book",
        "learn-spell",
        "cast-dragon-spell",
        "brew-potion",
        "use-artifact",
        "track-quest",
        "decline-quest",
        "choose-quest-branch",
        "persuade",
        "surrender",
        "report-crime",
        "recover-magicka",
        "identify-artifact",
        "appease-ancient-beast",
    } <= {handler.command_type for handler in dragon.commands.action_handlers}
    assert {
        "MapMarkerAddedEvent",
        "EncounterTriggeredEvent",
        "PerkUnlockedEvent",
        "GreatSoulAbsorbedEvent",
        "WordOfPowerLearnedEvent",
        "VoicePhraseInscribedEvent",
        "VoiceInscriptionStudiedEvent",
        "FactionRankChangedEvent",
        "GuardBribedEvent",
        "JailSentenceServedEvent",
        "LockPickedEvent",
        "LoreBookReadEvent",
        "SpellLearnedEvent",
        "DragonSpellCastEvent",
        "PotionBrewedEvent",
        "ArtifactUsedEvent",
        "QuestTrackedEvent",
        "QuestDeclinedEvent",
        "QuestBranchChosenEvent",
        "PersuasionAttemptedEvent",
        "SurrenderedEvent",
        "CrimeReportedEvent",
        "ArtifactIdentifiedEvent",
        "AncientBeastAppeasedEvent",
    } <= {event.__name__ for event in dragon.commands.typed_events}
    assert LIFESIM in dragon.dependencies.requires

    dagger = plugins[DAGGERSIM]
    assert {
        "InstitutionReputationComponent",
        "LegalReputationComponent",
        "ServiceAccessComponent",
        "PropertyDeedComponent",
        "InstitutionDuesComponent",
        "LetterOfCreditComponent",
        "SafeStorageComponent",
        "LodgingComponent",
        "CampingComponent",
        "PotionMakerComponent",
        "IngredientComponent",
        "AfflictionStigmaComponent",
    } <= {component.__name__ for component in dagger.ecs.components}
    assert "OwnsProperty" in {edge.__name__ for edge in dagger.ecs.edges}
    assert {
        "buy-property",
        "promote-institution",
        "pay-institution-dues",
        "refuse-generated-quest",
        "abandon-generated-quest",
        "extend-generated-quest",
        "lie-about-quest",
        "issue-letter-of-credit",
        "store-safe-item",
        "retrieve-safe-item",
        "send-debt-collector",
        "sentence-crime",
        "rent-lodging",
        "camp",
        "buy-travel-supplies",
        "resolve-travel-interruption",
        "make-potion",
        "recharge-enchanted-item",
        "identify-ingredient",
        "progress-affliction-incubation",
        "mark-affliction-stigma",
        "request-cure-quest",
    } <= {handler.command_type for handler in dagger.commands.action_handlers}
    assert {
        "InstitutionReputationChangedEvent",
        "LegalReputationChangedEvent",
        "ServiceAccessChangedEvent",
        "PropertyPurchasedEvent",
        "InstitutionPromotedEvent",
        "InstitutionDuesPaidEvent",
        "QuestRefusedEvent",
        "QuestAbandonedEvent",
        "QuestExtendedEvent",
        "LetterOfCreditIssuedEvent",
        "CourtSentenceIssuedEvent",
        "LodgingRentedEvent",
        "CampMadeEvent",
        "TravelInterruptionResolvedEvent",
        "PotionMadeEvent",
        "IngredientIdentifiedEvent",
        "AfflictionIncubationProgressedEvent",
        "AfflictionStigmaMarkedEvent",
        "CureQuestRequestedEvent",
    } <= {event.__name__ for event in dagger.commands.typed_events}

    void = plugins[VOIDSIM]
    assert {
        "DutyShiftComponent",
        "CrewDutyStatusComponent",
        "ContractComponent",
        "CargoComponent",
        "SalvageClaimComponent",
        "AlienSpeciesComponent",
        "FirstContactComponent",
        "TranslationMatrixComponent",
        "QuarantineComponent",
        "DiplomaticMissionComponent",
        "AlienArtifactComponent",
        "DroneComponent",
        "ShipAIComponent",
        "AwayTeamComponent",
        "MoraleComponent",
        "MutinyComponent",
        "EmergencyComponent",
        "ReactorComponent",
        "PassengerComponent",
        "SurveySiteComponent",
        "MiningSiteComponent",
        "MortgageComponent",
    } <= {component.__name__ for component in void.ecs.components}
    assert "WorksShift" in {edge.__name__ for edge in void.ecs.edges}
    assert {
        "assign-crew-shift",
        "relieve-crew-shift",
        "accept-contract",
        "load-cargo",
        "deliver-cargo",
        "claim-salvage",
        "initiate-contact",
        "attempt-translation",
        "quarantine-sample",
        "negotiate-alien",
        "study-alien-artifact",
        "deploy-away-team",
        "boost-morale",
        "start-mutiny",
        "command-drone",
        "hack-ship-ai",
        "salvage-data",
        "study-xenobiology",
        "accept-trade-protocol",
        "resolve-emergency",
        "stabilize-reactor",
        "adjust-gravity",
        "repel-boarders",
        "deliver-passenger",
        "survey-site",
        "mine-asteroid",
        "inspect-customs",
        "search-smuggling-compartment",
        "claim-insurance",
        "pay-mortgage",
    } <= {handler.command_type for handler in void.commands.action_handlers}
    assert {
        "CrewShiftAssignedEvent",
        "CrewDutyChangedEvent",
        "ContractAcceptedEvent",
        "CargoLoadedEvent",
        "CargoDeliveredEvent",
        "SalvageClaimedEvent",
        "FirstContactEvent",
        "TranslationProgressedEvent",
        "QuarantineStartedEvent",
        "DiplomacyChangedEvent",
        "AlienArtifactStudiedEvent",
        "AwayTeamDeployedEvent",
        "MoraleChangedEvent",
        "MutinyStartedEvent",
        "DroneCommandedEvent",
        "ShipAIHackedEvent",
        "DataSalvagedEvent",
        "XenobiologyStudiedEvent",
        "TradeProtocolAcceptedEvent",
        "EmergencyResolvedEvent",
        "ReactorStabilizedEvent",
        "GravityAdjustedEvent",
        "BoardingRepelledEvent",
        "PassengerDeliveredEvent",
        "SurveyCompletedEvent",
        "MiningCompletedEvent",
        "CustomsInspectedEvent",
        "SmugglingCompartmentSearchedEvent",
        "InsuranceClaimedEvent",
        "MortgagePaidEvent",
    } <= {event.__name__ for event in void.commands.typed_events}

    nuke = plugins[NUKESIM]
    assert {
        "OldWorldTechComponent",
        "TechLeadComponent",
        "SettlementComponent",
        "SettlementSalvageComponent",
        "WaterPurifierComponent",
        "GeneratorComponent",
        "HotspotMarkerComponent",
        "SuppressantComponent",
        "SampleComponent",
        "LockedCrateComponent",
        "WastelandArtifactComponent",
        "FactionSalvageComponent",
        "SchematicComponent",
        "ItemModComponent",
        "BeaconComponent",
        "RaiderPressureComponent",
        "TerminalComponent",
    } <= {component.__name__ for component in nuke.ecs.components}
    assert {
        "identify-tech",
        "restore-tech",
        "claim-settlement",
        "salvage-settlement",
        "build-purifier",
        "power-generator",
        "mark-hotspot",
        "use-suppressant",
        "harvest-sample",
        "study-sample",
        "unlock-crate",
        "study-wasteland-artifact",
        "claim-faction-salvage",
        "install-mod",
        "field-repair",
        "brew-chem",
        "activate-beacon",
        "open-trader-route",
        "increase-raider-pressure",
        "boot-terminal",
    } <= {handler.command_type for handler in nuke.commands.action_handlers}
    assert {
        "OldWorldTechIdentifiedEvent",
        "OldWorldTechRestoredEvent",
        "SettlementClaimedEvent",
        "SettlementSalvagedEvent",
        "PurifierBuiltEvent",
        "GeneratorPoweredEvent",
        "HotspotMarkedEvent",
        "SuppressantUsedEvent",
        "SampleHarvestedEvent",
        "SampleStudiedEvent",
        "CrateUnlockedEvent",
        "WastelandArtifactStudiedEvent",
        "FactionSalvageClaimedEvent",
        "ModInstalledEvent",
        "FieldRepairAppliedEvent",
        "ChemBrewedEvent",
        "BeaconActivatedEvent",
        "TraderRouteOpenedEvent",
        "RaiderPressureChangedEvent",
        "TerminalBootedEvent",
    } <= {event.__name__ for event in nuke.commands.typed_events}

    dino = plugins[DINOSIM]
    assert {
        "TerritoryComponent",
        "HerdComponent",
        "NestComponent",
        "FossilSurveyComponent",
        "LabIncubationComponent",
        "EggInspectionComponent",
        "ImprintComponent",
        "JuvenileCareComponent",
        "WaterCreatureComponent",
        "ContainmentPanicComponent",
    } <= {
        component.__name__ for component in dino.ecs.components
    }
    assert {
        "mark-territory",
        "track-herd",
        "prepare-nest",
        "survey-fossil",
        "excavate-fossil",
        "clean-fossil",
        "stabilize-fossil",
        "lab-incubate-egg",
        "inspect-egg",
        "imprint-creature",
        "care-for-juvenile",
        "study-water-creature",
        "brood-egg",
        "set-incubation-temperature",
        "trigger-containment-panic",
    } <= {
        handler.command_type for handler in dino.commands.action_handlers
    }
    assert {
        "TerritoryMarkedEvent",
        "HerdTrackedEvent",
        "NestPreparedEvent",
        "FossilSurveyedEvent",
        "FossilExcavatedEvent",
        "FossilCleanedEvent",
        "FossilStabilizedEvent",
        "LabIncubationStartedEvent",
        "EggInspectedEvent",
        "CreatureImprintedEvent",
        "JuvenileCareGivenEvent",
        "WaterCreatureStudiedEvent",
        "BroodingStartedEvent",
        "IncubationTemperatureSetEvent",
        "ContainmentPanicStartedEvent",
    } <= {
        event.__name__ for event in dino.commands.typed_events
    }

    neon = plugins[NEONSIM]
    assert {
        "CyberpunkSiteComponent",
        "SecurityZoneComponent",
        "AccessLevelComponent",
        "CheckpointComponent",
        "SafehouseComponent",
        "RestrictedAreaComponent",
    } <= {component.__name__ for component in neon.ecs.components}
    assert "InsideZone" in {edge.__name__ for edge in neon.ecs.edges}
    assert {
        "enter-district",
        "show-credentials",
        "bribe-checkpoint",
        "sneak-through-checkpoint",
        "claim-safehouse",
        "case-location",
    } <= {handler.command_type for handler in neon.commands.action_handlers}
    assert {
        "DistrictEnteredEvent",
        "AccessGrantedEvent",
        "AccessDeniedEvent",
        "CheckpointPassedEvent",
        "TrespassDetectedEvent",
        "SafehouseClaimedEvent",
    } <= {event.__name__ for event in neon.commands.typed_events}


def test_ecs_systems_can_be_instances_or_classes():
    # apply should accept a system instance as well as a class.
    from bunnyland.mechanics.needs import HungerSystem

    actor = WorldActor()
    plugin = Plugin(id="t", name="T", ecs=EcsContribution(systems=(HungerSystem(),)))
    apply_plugins([plugin], actor)  # must not raise


async def test_example_motd_plugin_greets_discord_claims_with_ecs_rows():
    from bunnyland.core.events import CharacterClaimedEvent
    from examples.plugins.motd_claim import HasMotdMessage, MotdMessageComponent

    scenario = build_scenario()
    plugins = select(load_modules(["examples.plugins.motd_claim"]), ["motd_claim"])
    apply_plugins(plugins, scenario.actor)
    controller = spawn_entity(
        scenario.actor.world,
        [DiscordControllerComponent(discord_user_id=123, default_channel_id=456)],
    )
    generation = scenario.actor.assign_controller(scenario.character, controller.id)

    await scenario.actor.bus.publish(
        CharacterClaimedEvent(
            **scenario.actor._event_base(
                actor_id=str(scenario.character),
                character_id=str(scenario.character),
                controller_id=str(controller.id),
                generation=generation,
            )
        )
    )
    await scenario.actor.tick(0.0)

    character = scenario.actor.world.get_entity(scenario.character)
    motds = [
        scenario.actor.world.get_entity(message_id)
        for _edge, message_id in character.get_relationships(HasMotdMessage)
    ]
    assert len(motds) == 1
    message = motds[0].get_component(MotdMessageComponent)
    assert "Today's tip" in message.text
    assert message.queued_for_delivery is True
    outbox = motds[0].get_component(ControllerOutboxMessageComponent)
    assert outbox.controller_id == str(controller.id)
    assert outbox.delivered_at_epoch is None


async def test_example_motd_plugin_ignores_non_discord_claims():
    from bunnyland.core.events import CharacterClaimedEvent
    from examples.plugins.motd_claim import HasMotdMessage

    scenario = build_scenario()
    plugins = select(load_modules(["examples.plugins.motd_claim"]), ["motd_claim"])
    apply_plugins(plugins, scenario.actor)

    await scenario.actor.bus.publish(
        CharacterClaimedEvent(
            **scenario.actor._event_base(
                actor_id=str(scenario.character),
                character_id=str(scenario.character),
                controller_id=str(scenario.controller),
                generation=scenario.generation,
            )
        )
    )

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_relationships(HasMotdMessage) == []


# -- helpers ----------------------------------------------------------------------------


def _bare_scenario():
    # build_scenario registers MoveHandler already; use a fresh actor with no handlers
    # by clearing the registry so we can prove plugins add them.
    scenario = build_scenario()
    scenario.actor._handlers.clear()
    return scenario


def _move(scenario):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
