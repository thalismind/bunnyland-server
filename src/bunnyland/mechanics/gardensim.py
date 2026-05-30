"""Garden-sim crop mechanics.

This first slice covers explicit soil preparation, planting, watering, fertilizer, crop
growth, and harvest. It intentionally avoids farm animals, machines, fishing, festivals,
and economy until the basic crop loop is solid.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pydantic.dataclasses import dataclass as pydantic_dataclass
from relics import Component, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import IdentityComponent, PortableComponent
from ..core.ecs import (
    container_of,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .environment import CalendarComponent

SECONDS_PER_DAY = 24 * 60 * 60


@pydantic_dataclass(frozen=True)
class SoilComponent(Component):
    quality: float = 1.0


@pydantic_dataclass(frozen=True)
class TilledComponent(Component):
    tilled_at_epoch: int


@pydantic_dataclass(frozen=True)
class WateredComponent(Component):
    watered_at_epoch: int
    expires_at_epoch: int


@pydantic_dataclass(frozen=True)
class FertilizerComponent(Component):
    kind: str = "basic"
    growth_multiplier: float = 1.0
    quality_bonus: float = 0.0


@pydantic_dataclass(frozen=True)
class SeedComponent(Component):
    crop_type: str
    growth_days: float
    yield_item: str
    yield_quantity: int = 1
    seasons: tuple[str, ...] = ("spring", "summer", "autumn")
    stage_count: int = 3


@pydantic_dataclass(frozen=True)
class CropComponent(Component):
    crop_type: str
    planted_at_epoch: int
    stage: int = 0
    ready: bool = False
    dead: bool = False
    seasons: tuple[str, ...] = ("spring", "summer", "autumn")


@pydantic_dataclass(frozen=True)
class CropGrowthComponent(Component):
    progress_days: float
    required_days: float
    last_updated_epoch: int
    stage_count: int = 3


@pydantic_dataclass(frozen=True)
class HarvestableComponent(Component):
    yield_item: str
    quantity: int = 1
    ready: bool = False


class SoilTilledEvent(DomainEvent):
    soil_id: str


class SeedPlantedEvent(DomainEvent):
    soil_id: str
    seed_id: str
    crop_type: str


class CropWateredEvent(DomainEvent):
    soil_id: str
    expires_at_epoch: int


class FertilizerAppliedEvent(DomainEvent):
    soil_id: str
    fertilizer_id: str
    kind: str


class CropGrewEvent(DomainEvent):
    soil_id: str
    crop_type: str
    stage: int
    progress_days: float


class CropReadyEvent(DomainEvent):
    soil_id: str
    crop_type: str


class CropWitheredEvent(DomainEvent):
    soil_id: str
    crop_type: str
    season: str


class CropHarvestedEvent(DomainEvent):
    soil_id: str
    crop_type: str
    item_id: str
    quantity: int


def _event_base(epoch: int, **kwargs) -> dict:
    base = {
        "event_id": uuid4().hex,
        "world_epoch": epoch,
        "created_at": datetime.now(UTC),
        "visibility": EventVisibility.ROOM,
    }
    base.update(kwargs)
    return base


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _entity_room_id(entity: Entity) -> str | None:
    raw = container_of(entity)
    return str(raw) if raw is not None else None


def _reachable_entity(ctx: HandlerContext, character_id: EntityId, target_id: EntityId):
    character = ctx.entity(character_id)
    if target_id not in reachable_ids(ctx.world, character):
        return None
    return ctx.entity(target_id)


def _remove_from_container(world: World, entity_id: EntityId) -> None:
    entity = world.get_entity(entity_id)
    parent_id = container_of(entity)
    if parent_id is not None:
        world.get_entity(parent_id).remove_relationship(Contains, entity_id)


def _spawn_harvest_item(
    world: World, character: Entity, crop_type: str, item_name: str, quantity: int
) -> str:
    label = f"{item_name} x{quantity}" if quantity != 1 else item_name
    item = spawn_entity(
        world,
        [
            IdentityComponent(name=label, kind="crop", tags=(crop_type,)),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _current_season(world: World) -> str | None:
    clocks = list(world.query().with_all([CalendarComponent]).execute_entities())
    if not clocks:
        return None
    return clocks[0].get_component(CalendarComponent).season


class CropGrowthConsequence:
    """Grow watered crops and wither crops that are out of season."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        season = _current_season(world)
        query = world.query().with_all([CropComponent, CropGrowthComponent])
        for soil in list(query.execute_entities()):
            crop = soil.get_component(CropComponent)
            growth = soil.get_component(CropGrowthComponent)
            if crop.dead or crop.ready:
                continue
            if season is not None and crop.seasons and season not in crop.seasons:
                replace_component(soil, replace(crop, dead=True, ready=False))
                if soil.has_component(HarvestableComponent):
                    soil.remove_component(HarvestableComponent)
                events.append(
                    CropWitheredEvent(
                        **_event_base(
                            epoch,
                            room_id=_entity_room_id(soil),
                            target_ids=(str(soil.id),),
                            soil_id=str(soil.id),
                            crop_type=crop.crop_type,
                            season=season,
                        )
                    )
                )
                continue

            if not soil.has_component(WateredComponent):
                if growth.last_updated_epoch != epoch:
                    replace_component(soil, replace(growth, last_updated_epoch=epoch))
                continue

            watered = soil.get_component(WateredComponent)
            growth_until = min(epoch, watered.expires_at_epoch)
            delta_days = max(0.0, (growth_until - growth.last_updated_epoch) / SECONDS_PER_DAY)
            fertilizer = (
                soil.get_component(FertilizerComponent)
                if soil.has_component(FertilizerComponent)
                else FertilizerComponent()
            )
            progress = growth.progress_days + delta_days * fertilizer.growth_multiplier
            stage = min(
                growth.stage_count,
                int((progress / growth.required_days) * growth.stage_count),
            )
            ready = progress >= growth.required_days
            updated_crop = replace(crop, stage=max(crop.stage, stage), ready=ready)
            updated_growth = replace(
                growth,
                progress_days=min(progress, growth.required_days),
                last_updated_epoch=epoch,
            )
            replace_component(soil, updated_crop)
            replace_component(soil, updated_growth)

            if soil.has_component(HarvestableComponent):
                harvestable = soil.get_component(HarvestableComponent)
                replace_component(soil, replace(harvestable, ready=ready))

            if updated_crop.stage != crop.stage:
                events.append(
                    CropGrewEvent(
                        **_event_base(
                            epoch,
                            room_id=_entity_room_id(soil),
                            target_ids=(str(soil.id),),
                            soil_id=str(soil.id),
                            crop_type=crop.crop_type,
                            stage=updated_crop.stage,
                            progress_days=round(updated_growth.progress_days, 3),
                        )
                    )
                )
            if ready and not crop.ready:
                events.append(
                    CropReadyEvent(
                        **_event_base(
                            epoch,
                            room_id=_entity_room_id(soil),
                            target_ids=(str(soil.id),),
                            soil_id=str(soil.id),
                            crop_type=crop.crop_type,
                        )
                    )
                )
            if watered.expires_at_epoch <= epoch:
                soil.remove_component(WateredComponent)
        return events


class TillHandler:
    command_type = "till"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(SoilComponent):
            return rejected("target is not soil")
        if soil.has_component(TilledComponent):
            return rejected("soil is already tilled")

        soil.add_component(TilledComponent(tilled_at_epoch=ctx.epoch))
        return ok(
            SoilTilledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                )
            )
        )


class PlantHandler:
    command_type = "plant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        seed_id = parse_entity_id(command.payload.get("seed_id"))
        if character_id is None or soil_id is None or seed_id is None:
            return rejected("invalid character, soil, or seed id")
        if not ctx.world.has_entity(soil_id) or not ctx.world.has_entity(seed_id):
            return rejected("soil or seed does not exist")

        soil = _reachable_entity(ctx, character_id, soil_id)
        seed_entity = _reachable_entity(ctx, character_id, seed_id)
        if soil is None or seed_entity is None:
            return rejected("soil or seed is not reachable")
        if not soil.has_component(SoilComponent) or not soil.has_component(TilledComponent):
            return rejected("soil is not prepared")
        if soil.has_component(CropComponent):
            return rejected("soil already has a crop")
        if not seed_entity.has_component(SeedComponent):
            return rejected("target seed is not plantable")

        seed = seed_entity.get_component(SeedComponent)
        soil.add_component(
            CropComponent(
                crop_type=seed.crop_type,
                planted_at_epoch=ctx.epoch,
                seasons=seed.seasons,
            )
        )
        soil.add_component(
            CropGrowthComponent(
                progress_days=0.0,
                required_days=seed.growth_days,
                last_updated_epoch=ctx.epoch,
                stage_count=seed.stage_count,
            )
        )
        soil.add_component(
            HarvestableComponent(
                yield_item=seed.yield_item,
                quantity=seed.yield_quantity,
                ready=False,
            )
        )
        _remove_from_container(ctx.world, seed_id)
        return ok(
            SeedPlantedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id), str(seed_id)),
                    soil_id=str(soil_id),
                    seed_id=str(seed_id),
                    crop_type=seed.crop_type,
                )
            )
        )


class WaterCropHandler:
    command_type = "water-crop"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(SoilComponent):
            return rejected("target is not soil")

        expires_at = ctx.epoch + SECONDS_PER_DAY
        replace_component(
            soil,
            WateredComponent(watered_at_epoch=ctx.epoch, expires_at_epoch=expires_at),
        )
        return ok(
            CropWateredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id),),
                    soil_id=str(soil_id),
                    expires_at_epoch=expires_at,
                )
            )
        )


class FertilizeHandler:
    command_type = "fertilize"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        fertilizer_id = parse_entity_id(command.payload.get("fertilizer_id"))
        if character_id is None or soil_id is None or fertilizer_id is None:
            return rejected("invalid character, soil, or fertilizer id")
        if not ctx.world.has_entity(soil_id) or not ctx.world.has_entity(fertilizer_id):
            return rejected("soil or fertilizer does not exist")
        soil = _reachable_entity(ctx, character_id, soil_id)
        fertilizer_entity = _reachable_entity(ctx, character_id, fertilizer_id)
        if soil is None or fertilizer_entity is None:
            return rejected("soil or fertilizer is not reachable")
        if not soil.has_component(SoilComponent):
            return rejected("target is not soil")
        if not fertilizer_entity.has_component(FertilizerComponent):
            return rejected("target fertilizer is not usable")

        fertilizer = fertilizer_entity.get_component(FertilizerComponent)
        replace_component(soil, fertilizer)
        _remove_from_container(ctx.world, fertilizer_id)
        return ok(
            FertilizerAppliedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id), str(fertilizer_id)),
                    soil_id=str(soil_id),
                    fertilizer_id=str(fertilizer_id),
                    kind=fertilizer.kind,
                )
            )
        )


class HarvestCropHandler:
    command_type = "harvest-crop"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        soil_id = parse_entity_id(command.payload.get("soil_id"))
        if character_id is None or soil_id is None:
            return rejected("invalid character or soil id")
        if not ctx.world.has_entity(soil_id):
            return rejected("soil does not exist")
        character = ctx.entity(character_id)
        soil = _reachable_entity(ctx, character_id, soil_id)
        if soil is None:
            return rejected("soil is not reachable")
        if not soil.has_component(CropComponent) or not soil.has_component(HarvestableComponent):
            return rejected("soil has no harvestable crop")

        crop = soil.get_component(CropComponent)
        harvestable = soil.get_component(HarvestableComponent)
        if crop.dead:
            return rejected("crop is dead")
        if not crop.ready or not harvestable.ready:
            return rejected("crop is not ready")

        item_id = _spawn_harvest_item(
            ctx.world,
            character,
            crop.crop_type,
            harvestable.yield_item,
            harvestable.quantity,
        )
        soil.remove_component(CropComponent)
        soil.remove_component(CropGrowthComponent)
        soil.remove_component(HarvestableComponent)
        if soil.has_component(WateredComponent):
            soil.remove_component(WateredComponent)
        return ok(
            CropHarvestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(soil_id), item_id),
                    soil_id=str(soil_id),
                    crop_type=crop.crop_type,
                    item_id=item_id,
                    quantity=harvestable.quantity,
                )
            )
        )


def gardensim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if not entity.has_component(SoilComponent):
            continue
        name = (
            entity.get_component(IdentityComponent).name
            if entity.has_component(IdentityComponent)
            else "soil"
        )
        if entity.has_component(CropComponent):
            crop = entity.get_component(CropComponent)
            state = "dead" if crop.dead else "ready" if crop.ready else f"stage {crop.stage}"
            lines.append(f"Nearby crop: {crop.crop_type} in {name} ({state}).")
        elif entity.has_component(TilledComponent):
            lines.append(f"Nearby tilled soil: {name}.")
        else:
            lines.append(f"Nearby soil: {name}.")
    return sorted(lines)


def install_gardensim(actor) -> None:
    actor.register_consequence(CropGrowthConsequence())


__all__ = [
    "CropComponent",
    "CropGrewEvent",
    "CropGrowthComponent",
    "CropGrowthConsequence",
    "CropHarvestedEvent",
    "CropReadyEvent",
    "CropWateredEvent",
    "CropWitheredEvent",
    "FertilizerAppliedEvent",
    "FertilizerComponent",
    "FertilizeHandler",
    "HarvestCropHandler",
    "HarvestableComponent",
    "PlantHandler",
    "SeedComponent",
    "SeedPlantedEvent",
    "SoilComponent",
    "SoilTilledEvent",
    "TilledComponent",
    "TillHandler",
    "WaterCropHandler",
    "WateredComponent",
    "gardensim_fragments",
    "install_gardensim",
]
