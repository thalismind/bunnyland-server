"""Neon-sim cyberpunk city mechanics (catalogue section 10).

This package leans on existing systems instead of becoming a second core: districts are
modelled with the core ``RegionComponent`` rather than a bespoke district type, and later
slices reuse dagger-sim law/reputation/debt. Implemented so far: cyberpunk sites, security
zones, access control, checkpoints, safehouses, and deterministic trespass detection
(catalogue 10.1); networked devices, cameras, drones, surveillance, recorded evidence, and
blind spots (catalogue 10.2).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    DeadComponent,
    IdentityComponent,
    RegionComponent,
    SuspendedComponent,
)
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
from .colonysim import ResourceStackComponent

SCRIP_RESOURCE = "scrip"


# --- Edges ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InsideZone(Edge):
    """character -> site. ``authorized`` is False when the entry slipped past access."""

    authorized: bool = True
    entered_epoch: int = 0


# --- Components (catalogue 10.1) ------------------------------------------------------


@dataclass(frozen=True)
class CyberpunkSiteComponent(Component):
    """Tags a location entity as an enterable neon-sim site."""

    site_type: str = "site"


@dataclass(frozen=True)
class SecurityZoneComponent(Component):
    """A site that demands clearance. ``controller`` names the faction/corp gate tag."""

    clearance_required: int = 1
    controller: str = ""
    alarm_raised: bool = False


@dataclass(frozen=True)
class AccessLevelComponent(Component):
    """A character's standing clearance plus any specific zone passes they hold."""

    clearance: int = 0
    passes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckpointComponent(Component):
    """A manned gate. ``zone_tag`` matches an :class:`AccessLevelComponent` pass."""

    clearance_required: int = 1
    bribe_cost: int = 0
    zone_tag: str = ""
    alerted: bool = False


@dataclass(frozen=True)
class SafehouseComponent(Component):
    claimed_by: str | None = None


@dataclass(frozen=True)
class PublicAccessComponent(Component):
    """Marker: anyone may enter regardless of any security zone on the same site."""


@dataclass(frozen=True)
class RestrictedAreaComponent(Component):
    """Marker: unauthorized presence here is hunted by ``TrespassDetectionConsequence``."""

    patrol: bool = True


# --- Events --------------------------------------------------------------------------


class DistrictEnteredEvent(DomainEvent):
    character_id: str
    site_id: str
    site_type: str
    district: str = ""


class AccessGrantedEvent(DomainEvent):
    character_id: str
    site_id: str
    method: str = "clearance"


class AccessDeniedEvent(DomainEvent):
    character_id: str
    site_id: str
    requirement: int = 0


class CheckpointPassedEvent(DomainEvent):
    character_id: str
    checkpoint_id: str
    method: str = "credentials"


class TrespassDetectedEvent(DomainEvent):
    character_id: str
    site_id: str
    site_type: str


class SafehouseClaimedEvent(DomainEvent):
    character_id: str
    safehouse_id: str


class LocationCasedEvent(DomainEvent):
    character_id: str
    site_id: str
    clearance_required: int
    restricted: bool
    has_checkpoint: bool


# --- Helpers -------------------------------------------------------------------------


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


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


def _district_name(world: World, character_id: EntityId) -> str:
    room_id = container_of(world.get_entity(character_id))
    if room_id is not None and world.has_entity(room_id):
        room = world.get_entity(room_id)
        if room.has_component(RegionComponent):
            return room.get_component(RegionComponent).name
    return ""


def _reachable_component(ctx: HandlerContext, character_id: EntityId, target_id, component):
    parsed = parse_entity_id(target_id)
    if parsed is None or not ctx.world.has_entity(parsed):
        return None, "target does not exist"
    character = ctx.entity(character_id)
    if parsed not in reachable_ids(ctx.world, character):
        return None, "target is not reachable"
    entity = ctx.entity(parsed)
    if not entity.has_component(component):
        return None, "target is the wrong kind"
    return entity, None


def _truthy(value) -> bool:
    """Parse an optional payload flag that may arrive as a bool or a string."""
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _access_level(character: Entity) -> AccessLevelComponent:
    if character.has_component(AccessLevelComponent):
        return character.get_component(AccessLevelComponent)
    return AccessLevelComponent()


def _has_clearance(character: Entity, clearance_required: int, zone_tag: str) -> bool:
    access = _access_level(character)
    if zone_tag and zone_tag in access.passes:
        return True
    return access.clearance >= clearance_required


def _clear_inside_zones(character: Entity) -> None:
    for _edge, site_id in list(character.get_relationships(InsideZone)):
        character.remove_relationship(InsideZone, site_id)


def _spend_scrip(character: Entity, world: World, amount: int) -> bool:
    if amount <= 0:
        return True
    for _edge, item_id in character.get_relationships(Contains):
        if not world.has_entity(item_id):
            continue
        item = world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == SCRIP_RESOURCE
        ):
            stack = item.get_component(ResourceStackComponent)
            if stack.quantity < amount:
                return False
            remaining = stack.quantity - amount
            if remaining > 0:
                replace_component(item, replace(stack, quantity=remaining))
                replace_component(
                    item,
                    IdentityComponent(name=f"{SCRIP_RESOURCE} x{remaining}", kind="resource"),
                )
            else:
                parent_id = container_of(item)
                if parent_id is not None and world.has_entity(parent_id):
                    world.get_entity(parent_id).remove_relationship(Contains, item_id)
            return True
    return False


# --- Consequences (catalogue 10.1 systems) -------------------------------------------


class TrespassDetectionConsequence:
    """Patrols catch unauthorized presence in restricted areas, deterministically.

    An unauthorized ``InsideZone`` edge into a patrolled restricted area trips the alarm
    on the next tick, emits a :class:`TrespassDetectedEvent`, and ejects the intruder so
    the detection fires exactly once.
    """

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in (
            world.query()
            .with_all([CharacterComponent])
            .with_none([DeadComponent, SuspendedComponent])
            .execute_entities()
        ):
            for edge, site_id in list(character.get_relationships(InsideZone)):
                if edge.authorized or not world.has_entity(site_id):
                    continue
                site = world.get_entity(site_id)
                if not site.has_component(RestrictedAreaComponent):
                    continue
                if not site.get_component(RestrictedAreaComponent).patrol:
                    continue
                site_type = (
                    site.get_component(CyberpunkSiteComponent).site_type
                    if site.has_component(CyberpunkSiteComponent)
                    else "restricted area"
                )
                if site.has_component(SecurityZoneComponent):
                    zone = site.get_component(SecurityZoneComponent)
                    replace_component(site, replace(zone, alarm_raised=True))
                character.remove_relationship(InsideZone, site_id)
                events.append(
                    TrespassDetectedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            target_ids=(str(site_id),),
                            character_id=str(character.id),
                            site_id=str(site_id),
                            site_type=site_type,
                        )
                    )
                )
        return events


# --- Handlers (catalogue 10.1 actions) -----------------------------------------------


class EnterDistrictHandler:
    command_type = "enter-district"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        site, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CyberpunkSiteComponent
        )
        if site is None:
            return rejected(error if error else "target is not a site")

        covert = _truthy(command.payload.get("covert", False))
        character = ctx.entity(character_id)
        site_type = site.get_component(CyberpunkSiteComponent).site_type
        clearance_required = 0
        zone_tag = ""
        if site.has_component(SecurityZoneComponent):
            zone = site.get_component(SecurityZoneComponent)
            clearance_required = zone.clearance_required
            zone_tag = zone.controller

        open_site = site.has_component(PublicAccessComponent) or clearance_required <= 0
        authorized = open_site or _has_clearance(character, clearance_required, zone_tag)

        if not authorized and not covert:
            return ok(
                AccessDeniedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(site.id),),
                        character_id=str(character_id),
                        site_id=str(site.id),
                        requirement=clearance_required,
                    )
                )
            )

        _clear_inside_zones(character)
        character.add_relationship(
            InsideZone(authorized=authorized, entered_epoch=ctx.epoch), site.id
        )
        events: list[DomainEvent] = [
            DistrictEnteredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site.id),),
                    character_id=str(character_id),
                    site_id=str(site.id),
                    site_type=site_type,
                    district=_district_name(ctx.world, character_id),
                )
            )
        ]
        if authorized:
            events.append(
                AccessGrantedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(site.id),),
                        character_id=str(character_id),
                        site_id=str(site.id),
                        method="public" if open_site else "clearance",
                    )
                )
            )
        return ok(*events)


class ShowCredentialsHandler:
    command_type = "show-credentials"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        checkpoint, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CheckpointComponent
        )
        if checkpoint is None:
            return rejected(error if error else "target is not a checkpoint")
        gate = checkpoint.get_component(CheckpointComponent)
        character = ctx.entity(character_id)
        if not _has_clearance(character, gate.clearance_required, gate.zone_tag):
            return ok(
                AccessDeniedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(checkpoint.id),),
                        character_id=str(character_id),
                        site_id=str(checkpoint.id),
                        requirement=gate.clearance_required,
                    )
                )
            )
        return ok(
            CheckpointPassedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(checkpoint.id),),
                    character_id=str(character_id),
                    checkpoint_id=str(checkpoint.id),
                    method="credentials",
                )
            ),
            AccessGrantedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(checkpoint.id),),
                    character_id=str(character_id),
                    site_id=str(checkpoint.id),
                    method="credentials",
                )
            ),
        )


class BribeCheckpointHandler:
    command_type = "bribe-checkpoint"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        checkpoint, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CheckpointComponent
        )
        if checkpoint is None:
            return rejected(error if error else "target is not a checkpoint")
        gate = checkpoint.get_component(CheckpointComponent)
        if gate.bribe_cost <= 0:
            return rejected("this checkpoint has no guard to bribe")
        character = ctx.entity(character_id)
        if not _spend_scrip(character, ctx.world, gate.bribe_cost):
            return rejected("not enough scrip to bribe the guard")
        if gate.alerted:
            replace_component(checkpoint, replace(gate, alerted=False))
        return ok(
            CheckpointPassedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(checkpoint.id),),
                    character_id=str(character_id),
                    checkpoint_id=str(checkpoint.id),
                    method="bribe",
                )
            ),
            AccessGrantedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(checkpoint.id),),
                    character_id=str(character_id),
                    site_id=str(checkpoint.id),
                    method="bribe",
                )
            ),
        )


class SneakCheckpointHandler:
    command_type = "sneak-through-checkpoint"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        checkpoint, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CheckpointComponent
        )
        if checkpoint is None:
            return rejected(error if error else "target is not a checkpoint")
        gate = checkpoint.get_component(CheckpointComponent)
        if gate.alerted:
            return rejected("the checkpoint guard is watching too closely")
        character = ctx.entity(character_id)
        if _has_clearance(character, gate.clearance_required, gate.zone_tag):
            return rejected("you can simply show credentials here")
        return ok(
            CheckpointPassedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(checkpoint.id),),
                    character_id=str(character_id),
                    checkpoint_id=str(checkpoint.id),
                    method="stealth",
                )
            )
        )


class ClaimSafehouseHandler:
    command_type = "claim-safehouse"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        safehouse, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), SafehouseComponent
        )
        if safehouse is None:
            return rejected(error if error else "target is not a safehouse")
        component = safehouse.get_component(SafehouseComponent)
        if component.claimed_by == str(character_id):
            return rejected("you already hold this safehouse")
        if component.claimed_by is not None:
            return rejected("safehouse is already claimed")
        replace_component(safehouse, replace(component, claimed_by=str(character_id)))
        return ok(
            SafehouseClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(safehouse.id),),
                    character_id=str(character_id),
                    safehouse_id=str(safehouse.id),
                )
            )
        )


class CaseLocationHandler:
    command_type = "case-location"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        site, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CyberpunkSiteComponent
        )
        if site is None:
            return rejected(error if error else "target is not a site")
        clearance_required = (
            site.get_component(SecurityZoneComponent).clearance_required
            if site.has_component(SecurityZoneComponent)
            else 0
        )
        has_checkpoint = any(
            ctx.world.get_entity(reachable_id).has_component(CheckpointComponent)
            for reachable_id in reachable_ids(ctx.world, ctx.entity(character_id))
            if ctx.world.has_entity(reachable_id)
        )
        return ok(
            LocationCasedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site.id),),
                    character_id=str(character_id),
                    site_id=str(site.id),
                    clearance_required=clearance_required,
                    restricted=site.has_component(RestrictedAreaComponent),
                    has_checkpoint=has_checkpoint,
                )
            )
        )


# --- Components (catalogue 10.2: devices, networks, surveillance) --------------------


@dataclass(frozen=True)
class DeviceComponent(Component):
    """A networked device. ``device_type`` covers camera/sensor/drone/terminal/etc."""

    device_type: str = "device"
    powered: bool = True
    disabled: bool = False
    owner: str = ""


@dataclass(frozen=True)
class CameraComponent(Component):
    """Camera-specific state. ``looped`` feeds a fake signal so it records nothing."""

    looped: bool = False


@dataclass(frozen=True)
class SurveillanceCoverageComponent(Component):
    """Marks a device as actively watching its room and able to record evidence."""

    coverage: float = 1.0


@dataclass(frozen=True)
class DroneComponent(Component):
    deployed: bool = False


@dataclass(frozen=True)
class RecordedEvidenceComponent(Component):
    subject_id: str
    device_id: str
    device_type: str = "camera"
    wiped: bool = False


@dataclass(frozen=True)
class BlindSpotComponent(Component):
    """Marker on a site: cameras cannot record intruders sheltering inside it."""


# --- Events (catalogue 10.2) ---------------------------------------------------------


class DeviceInspectedEvent(DomainEvent):
    character_id: str
    device_id: str
    device_type: str
    powered: bool
    disabled: bool


class CameraDisabledEvent(DomainEvent):
    character_id: str
    device_id: str


class CameraLoopedEvent(DomainEvent):
    character_id: str
    device_id: str


class SensorJammedEvent(DomainEvent):
    character_id: str
    device_id: str


class DroneDeployedEvent(DomainEvent):
    character_id: str
    device_id: str


class EvidenceRecordedEvent(DomainEvent):
    character_id: str
    device_id: str
    evidence_id: str


class EvidenceWipedEvent(DomainEvent):
    character_id: str
    evidence_id: str


# --- Device helpers ------------------------------------------------------------------


def _reachable_device(ctx: HandlerContext, character_id: EntityId, target_id, device_type=None):
    entity, error = _reachable_component(ctx, character_id, target_id, DeviceComponent)
    if entity is None:
        return None, error
    if device_type is not None and entity.get_component(DeviceComponent).device_type != device_type:
        return None, f"target is not a {device_type}"
    return entity, None


def _device(entity: Entity) -> DeviceComponent | None:
    return entity.get_component(DeviceComponent) if entity.has_component(DeviceComponent) else None


def _evidence_for(world: World, subject_id: str, device_id: str) -> Entity | None:
    for record in world.query().with_all([RecordedEvidenceComponent]).execute_entities():
        component = record.get_component(RecordedEvidenceComponent)
        if (
            not component.wiped
            and component.subject_id == subject_id
            and component.device_id == device_id
        ):
            return record
    return None


def _unauthorized_sites(character: Entity) -> list[EntityId]:
    return [
        site_id
        for edge, site_id in character.get_relationships(InsideZone)
        if not edge.authorized
    ]


# --- Consequences (catalogue 10.2 systems) -------------------------------------------


class SurveillanceConsequence:
    """Active cameras and drones record evidence of unauthorized intruders nearby.

    Registered before :class:`TrespassDetectionConsequence` so a covert intruder is
    filmed on the same tick they are caught. Looping, disabling, or jamming a device
    first, or sheltering in a blind-spot site, prevents the recording.
    """

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for device in (
            world.query()
            .with_all([DeviceComponent, SurveillanceCoverageComponent])
            .execute_entities()
        ):
            dev = device.get_component(DeviceComponent)
            if not dev.powered or dev.disabled:
                continue
            if device.has_component(CameraComponent):
                if device.get_component(CameraComponent).looped:
                    continue
            room_id = container_of(device)
            if room_id is None or not world.has_entity(room_id):
                continue
            for character in (
                world.query()
                .with_all([CharacterComponent])
                .with_none([DeadComponent, SuspendedComponent])
                .execute_entities()
            ):
                if container_of(character) != room_id:
                    continue
                sites = _unauthorized_sites(character)
                if not sites:
                    continue
                if any(
                    world.has_entity(site_id)
                    and world.get_entity(site_id).has_component(BlindSpotComponent)
                    for site_id in sites
                ):
                    continue
                if _evidence_for(world, str(character.id), str(device.id)) is not None:
                    continue
                evidence = spawn_entity(
                    world,
                    [
                        IdentityComponent(name=f"footage of {_name(character)}", kind="evidence"),
                        RecordedEvidenceComponent(
                            subject_id=str(character.id),
                            device_id=str(device.id),
                            device_type=dev.device_type,
                        ),
                    ],
                )
                world.get_entity(room_id).add_relationship(
                    Contains(mode=ContainmentMode.ROOM_CONTENT), evidence.id
                )
                events.append(
                    EvidenceRecordedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(device.id),
                            room_id=str(room_id),
                            target_ids=(str(character.id), str(evidence.id)),
                            character_id=str(character.id),
                            device_id=str(device.id),
                            evidence_id=str(evidence.id),
                        )
                    )
                )
        return events


# --- Handlers (catalogue 10.2 actions) -----------------------------------------------


class InspectDeviceHandler:
    command_type = "inspect-device"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_device(ctx, character_id, command.payload.get("target_id"))
        if device is None:
            return rejected(error if error else "target is not a device")
        dev = device.get_component(DeviceComponent)
        return ok(
            DeviceInspectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                    device_type=dev.device_type,
                    powered=dev.powered,
                    disabled=dev.disabled,
                )
            )
        )


class DisableCameraHandler:
    command_type = "disable-camera"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CameraComponent
        )
        if device is None:
            return rejected(error if error else "target is not a camera")
        dev = _device(device)
        if dev is None:
            return rejected("target is not a camera")
        if dev.disabled:
            return rejected("camera is already disabled")
        replace_component(device, replace(dev, disabled=True))
        return ok(
            CameraDisabledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                )
            )
        )


class LoopCameraHandler:
    command_type = "loop-camera"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CameraComponent
        )
        if device is None:
            return rejected(error if error else "target is not a camera")
        camera = device.get_component(CameraComponent)
        dev = _device(device)
        if dev is not None and (not dev.powered or dev.disabled):
            return rejected("camera is offline")
        if camera.looped:
            return rejected("camera is already looped")
        replace_component(device, replace(camera, looped=True))
        return ok(
            CameraLoopedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                )
            )
        )


class JamSensorHandler:
    command_type = "jam-sensor"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_device(
            ctx, character_id, command.payload.get("target_id"), device_type="sensor"
        )
        if device is None:
            return rejected(error if error else "target is not a sensor")
        dev = device.get_component(DeviceComponent)
        if dev.disabled:
            return rejected("sensor is already jammed")
        replace_component(device, replace(dev, disabled=True))
        return ok(
            SensorJammedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                )
            )
        )


class DeployDroneHandler:
    command_type = "deploy-drone"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), DroneComponent
        )
        if device is None:
            return rejected(error if error else "target is not a drone")
        drone = device.get_component(DroneComponent)
        if drone.deployed:
            return rejected("drone is already deployed")
        replace_component(device, replace(drone, deployed=True))
        if device.has_component(DeviceComponent):
            dev = device.get_component(DeviceComponent)
            if not dev.powered:
                replace_component(device, replace(dev, powered=True))
        return ok(
            DroneDeployedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                )
            )
        )


class WipeEvidenceHandler:
    command_type = "wipe-evidence"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        record, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), RecordedEvidenceComponent
        )
        if record is None:
            return rejected(error if error else "target is not recorded evidence")
        component = record.get_component(RecordedEvidenceComponent)
        if component.wiped:
            return rejected("evidence is already wiped")
        evidence_id = str(record.id)
        parent_id = container_of(record)
        if parent_id is not None and ctx.world.has_entity(parent_id):
            ctx.world.get_entity(parent_id).remove_relationship(Contains, record.id)
        ctx.world.remove(record.id)
        return ok(
            EvidenceWipedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(evidence_id,),
                    character_id=str(character_id),
                    evidence_id=evidence_id,
                )
            )
        )


# --- Prompt fragments ----------------------------------------------------------------


def neonsim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    if character.has_component(AccessLevelComponent):
        access = character.get_component(AccessLevelComponent)
        if access.clearance > 0 or access.passes:
            passes = f", passes: {', '.join(access.passes)}" if access.passes else ""
            lines.append(f"Security clearance: level {access.clearance}{passes}.")

    inside = {site_id for _edge, site_id in character.get_relationships(InsideZone)}
    for entity_id in reachable_ids(world, character):
        if not world.has_entity(entity_id):
            continue
        entity = world.get_entity(entity_id)
        if entity.has_component(CyberpunkSiteComponent):
            site = entity.get_component(CyberpunkSiteComponent)
            tags = []
            if entity.has_component(SecurityZoneComponent):
                zone = entity.get_component(SecurityZoneComponent)
                tags.append(f"clearance {zone.clearance_required}")
                if zone.alarm_raised:
                    tags.append("ALARM")
            if entity.has_component(PublicAccessComponent):
                tags.append("public")
            if entity.has_component(RestrictedAreaComponent):
                tags.append("restricted")
            if entity_id in inside:
                tags.append("you are inside")
            suffix = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"Site {_name(entity)}: {site.site_type}{suffix}.")
        if entity.has_component(CheckpointComponent):
            gate = entity.get_component(CheckpointComponent)
            state = "alerted" if gate.alerted else "calm"
            bribe = f", bribe {gate.bribe_cost} scrip" if gate.bribe_cost > 0 else ""
            lines.append(
                f"Checkpoint {_name(entity)}: clearance {gate.clearance_required}, "
                f"{state}{bribe}."
            )
        if entity.has_component(SafehouseComponent):
            owner = entity.get_component(SafehouseComponent).claimed_by
            state = "unclaimed" if owner is None else "claimed"
            lines.append(f"Safehouse {_name(entity)}: {state}.")
        if entity.has_component(DeviceComponent):
            dev = entity.get_component(DeviceComponent)
            states = []
            if not dev.powered:
                states.append("unpowered")
            if dev.disabled:
                states.append("disabled")
            if entity.has_component(CameraComponent):
                if entity.get_component(CameraComponent).looped:
                    states.append("looped")
            if entity.has_component(SurveillanceCoverageComponent) and not states:
                states.append("watching")
            suffix = f" ({', '.join(states)})" if states else ""
            lines.append(f"Device {_name(entity)}: {dev.device_type}{suffix}.")
        if entity.has_component(RecordedEvidenceComponent):
            record = entity.get_component(RecordedEvidenceComponent)
            if not record.wiped:
                lines.append(f"Recorded evidence: {_name(entity)} ({record.device_type}).")
    return sorted(lines)


# --- Installation --------------------------------------------------------------------


def install_neonsim(actor) -> None:
    # Surveillance runs before trespass detection so a covert intruder is filmed on the
    # same tick they are caught and ejected.
    actor.register_consequence(SurveillanceConsequence())
    actor.register_consequence(TrespassDetectionConsequence())


__all__ = [
    "AccessDeniedEvent",
    "AccessGrantedEvent",
    "AccessLevelComponent",
    "BlindSpotComponent",
    "BribeCheckpointHandler",
    "CameraComponent",
    "CameraDisabledEvent",
    "CameraLoopedEvent",
    "CaseLocationHandler",
    "CheckpointComponent",
    "CheckpointPassedEvent",
    "ClaimSafehouseHandler",
    "CyberpunkSiteComponent",
    "DeviceComponent",
    "DeviceInspectedEvent",
    "DisableCameraHandler",
    "DeployDroneHandler",
    "DistrictEnteredEvent",
    "DroneComponent",
    "DroneDeployedEvent",
    "EnterDistrictHandler",
    "EvidenceRecordedEvent",
    "EvidenceWipedEvent",
    "InsideZone",
    "InspectDeviceHandler",
    "JamSensorHandler",
    "LocationCasedEvent",
    "LoopCameraHandler",
    "PublicAccessComponent",
    "RecordedEvidenceComponent",
    "RestrictedAreaComponent",
    "SafehouseClaimedEvent",
    "SafehouseComponent",
    "SecurityZoneComponent",
    "SensorJammedEvent",
    "ShowCredentialsHandler",
    "SneakCheckpointHandler",
    "SurveillanceConsequence",
    "SurveillanceCoverageComponent",
    "TrespassDetectedEvent",
    "TrespassDetectionConsequence",
    "WipeEvidenceHandler",
    "install_neonsim",
    "neonsim_fragments",
]
