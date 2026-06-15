"""Shared verb dispatch predicates for sim-specific handlers."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    HandlerContext,
    IdentityComponent,
    Lane,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.mechanics.daggersim import IdentifyIngredientHandler, IngredientComponent
from bunnyland.mechanics.dinosim import (
    CreatureMilkComponent,
    EggComponent,
    FossilFragmentComponent,
    HarvestProductHandler,
    IdentifyFossilHandler,
    InspectEggHandler,
)
from bunnyland.mechanics.dragonsim import (
    ArtifactComponent,
    BribeGuardHandler,
    GuardComponent,
    IdentifyArtifactHandler,
)
from bunnyland.mechanics.gardensim import (
    CropComponent,
    HarvestableComponent,
    HarvestCropHandler,
    HarvestSapHandler,
    InspectCropHandler,
    TreeComponent,
)
from bunnyland.mechanics.neonsim import (
    BribeCheckpointHandler,
    CheckpointComponent,
    DeviceComponent,
    HackableComponent,
    InspectDeviceHandler,
    SneakCheckpointHandler,
    UnlockDoorHandler,
)
from bunnyland.mechanics.nukesim import (
    DrinkContaminatedWaterHandler,
    IdentifyTechHandler,
    LockedCrateComponent,
    OldWorldTechComponent,
    RadMedicineComponent,
    UnlockCrateHandler,
    UseRadMedicineHandler,
    WaterPurityComponent,
)
from bunnyland.mechanics.voidsim import (
    CustomsHoldComponent,
    InspectCustomsHandler,
    InspectShipSystemHandler,
    ShipSystemComponent,
)


def _cmd(scenario, command_type: str, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _room_entity(scenario, name: str, kind: str, components):
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind=kind), *components],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


def _target_id(entity):
    return {"target_id": str(entity.id)}


def _item_id(entity):
    return {"item_id": str(entity.id)}


def test_shared_verb_handlers_accept_target_id_for_matching_components():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    cases = [
        (
            InspectCropHandler(),
            "inspect",
            _target_id(
                _room_entity(
                    scenario,
                    "bed",
                    "soil",
                    [CropComponent(crop_type="radish", planted_at_epoch=0)],
                )
            ),
        ),
        (
            HarvestCropHandler(),
            "harvest",
            _target_id(
                _room_entity(
                    scenario,
                    "ready bed",
                    "soil",
                    [
                        CropComponent(crop_type="radish", planted_at_epoch=0, ready=True),
                        HarvestableComponent(yield_item="radish", ready=True),
                    ],
                )
            ),
        ),
        (
            HarvestSapHandler(),
            "harvest",
            _target_id(
                _room_entity(
                    scenario,
                    "maple",
                    "tree",
                    [
                        TreeComponent(
                            tree_type="maple",
                            planted_at_epoch=0,
                            maturity_days=10.0,
                            mature=True,
                        ),
                        HarvestableComponent(yield_item="sap", ready=True),
                    ],
                )
            ),
        ),
        (
            UseRadMedicineHandler(),
            "use",
            _item_id(
                _room_entity(scenario, "rad-away", "medicine", [RadMedicineComponent()])
            ),
        ),
        (
            DrinkContaminatedWaterHandler(),
            "drink",
            _target_id(_room_entity(scenario, "spring", "water", [WaterPurityComponent()])),
        ),
        (
            UnlockCrateHandler(),
            "unlock",
            _target_id(_room_entity(scenario, "crate", "crate", [LockedCrateComponent()])),
        ),
        (
            IdentifyTechHandler(),
            "identify",
            _target_id(
                _room_entity(
                    scenario,
                    "device",
                    "tech",
                    [OldWorldTechComponent(tech_name="relay")],
                )
            ),
        ),
        (
            BribeCheckpointHandler(),
            "bribe",
            _target_id(_room_entity(scenario, "gate", "checkpoint", [CheckpointComponent()])),
        ),
        (
            SneakCheckpointHandler(),
            "sneak",
            _target_id(
                _room_entity(scenario, "quiet gate", "checkpoint", [CheckpointComponent()])
            ),
        ),
        (
            InspectDeviceHandler(),
            "inspect",
            _target_id(_room_entity(scenario, "camera", "device", [DeviceComponent()])),
        ),
        (
            UnlockDoorHandler(),
            "unlock",
            _target_id(_room_entity(scenario, "maglock", "device", [HackableComponent()])),
        ),
        (
            BribeGuardHandler(),
            "bribe",
            _target_id(
                _room_entity(scenario, "guard", "guard", [GuardComponent(faction_id="hold")])
            ),
        ),
        (
            IdentifyArtifactHandler(),
            "identify",
            _target_id(
                _room_entity(
                    scenario,
                    "mirror",
                    "artifact",
                    [ArtifactComponent(name="mirror")],
                )
            ),
        ),
        (
            IdentifyFossilHandler(),
            "identify",
            _target_id(_room_entity(scenario, "bone", "fossil", [FossilFragmentComponent()])),
        ),
        (
            InspectEggHandler(),
            "inspect",
            _target_id(
                _room_entity(
                    scenario,
                    "egg",
                    "egg",
                    [EggComponent(species_name="raptor", laid_at_epoch=0)],
                )
            ),
        ),
        (
            HarvestProductHandler(),
            "harvest",
            _target_id(
                _room_entity(scenario, "raptor", "creature", [CreatureMilkComponent()])
            ),
        ),
        (
            IdentifyIngredientHandler(),
            "identify",
            _target_id(
                _room_entity(
                    scenario,
                    "moon sugar",
                    "ingredient",
                    [IngredientComponent(ingredient_name="moon sugar", effect="sweet")],
                )
            ),
        ),
        (
            InspectShipSystemHandler(),
            "inspect",
            _target_id(
                _room_entity(
                    scenario,
                    "life support",
                    "ship-system",
                    [ShipSystemComponent(system_type="life-support")],
                )
            ),
        ),
        (
            InspectCustomsHandler(),
            "inspect",
            _target_id(_room_entity(scenario, "cargo hold", "hold", [CustomsHoldComponent()])),
        ),
    ]

    for handler, command_type, payload in cases:
        assert handler.can_handle(ctx, _cmd(scenario, command_type, **payload))


def test_shared_verb_handlers_accept_legacy_aliases_for_validation():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)

    cases = [
        (InspectCropHandler(), "inspect", {"soil_id": "not-an-id"}),
        (HarvestCropHandler(), "harvest", {"soil_id": "not-an-id"}),
        (HarvestSapHandler(), "harvest", {"tree_id": "not-an-id"}),
        (UseRadMedicineHandler(), "use", {"item_id": "not-an-id"}),
        (DrinkContaminatedWaterHandler(), "drink", {"water_id": "not-an-id"}),
        (UnlockCrateHandler(), "unlock", {"crate_id": "not-an-id"}),
        (IdentifyTechHandler(), "identify", {"tech_id": "not-an-id"}),
        (BribeCheckpointHandler(), "bribe", {"checkpoint_id": "not-an-id"}),
        (SneakCheckpointHandler(), "sneak", {"checkpoint_id": "not-an-id"}),
        (InspectDeviceHandler(), "inspect", {"device_id": "not-an-id"}),
        (UnlockDoorHandler(), "unlock", {"device_id": "not-an-id"}),
        (BribeGuardHandler(), "bribe", {"guard_id": "not-an-id"}),
        (IdentifyArtifactHandler(), "identify", {"artifact_id": "not-an-id"}),
        (IdentifyFossilHandler(), "identify", {"fossil_id": "not-an-id"}),
        (InspectEggHandler(), "inspect", {"egg_id": "not-an-id"}),
        (HarvestProductHandler(), "harvest", {"creature_id": "not-an-id"}),
        (IdentifyIngredientHandler(), "identify", {"ingredient_id": "not-an-id"}),
        (InspectShipSystemHandler(), "inspect", {"system_id": "not-an-id"}),
        (InspectCustomsHandler(), "inspect", {"hold_id": "not-an-id"}),
    ]

    for handler, command_type, payload in cases:
        assert handler.can_handle(ctx, _cmd(scenario, command_type, **payload))


def test_shared_verb_handlers_decline_reachable_wrong_kind_targets():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    plain = _room_entity(scenario, "plain rock", "rock", [])

    for handler, command_type in (
        (InspectCropHandler(), "inspect"),
        (HarvestCropHandler(), "harvest"),
        (HarvestSapHandler(), "harvest"),
        (UseRadMedicineHandler(), "use"),
        (DrinkContaminatedWaterHandler(), "drink"),
        (UnlockCrateHandler(), "unlock"),
        (IdentifyTechHandler(), "identify"),
        (BribeCheckpointHandler(), "bribe"),
        (SneakCheckpointHandler(), "sneak"),
        (InspectDeviceHandler(), "inspect"),
        (UnlockDoorHandler(), "unlock"),
        (BribeGuardHandler(), "bribe"),
        (IdentifyArtifactHandler(), "identify"),
        (IdentifyFossilHandler(), "identify"),
        (InspectEggHandler(), "inspect"),
        (HarvestProductHandler(), "harvest"),
        (IdentifyIngredientHandler(), "identify"),
        (InspectShipSystemHandler(), "inspect"),
        (InspectCustomsHandler(), "inspect"),
    ):
        assert not handler.can_handle(
            ctx, _cmd(scenario, command_type, target_id=str(plain.id))
        )
