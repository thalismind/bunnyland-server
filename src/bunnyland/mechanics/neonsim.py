"""Neon-sim cyberpunk city mechanics (catalogue section 10).

This package leans on existing systems instead of becoming a second core: districts are
modelled with the core ``RegionComponent`` rather than a bespoke district type, and later
slices reuse dagger-sim law/reputation/debt. Implemented so far: cyberpunk sites, security
zones, access control, checkpoints, safehouses, and deterministic trespass detection
(catalogue 10.1); networked devices, cameras, drones, surveillance, recorded evidence, and
blind spots (catalogue 10.2); hacking, credentials, exploits, backdoors, data exfiltration,
sabotage, and a counter-intrusion trace timer (catalogue 10.3); and a street economy with
contraband, data fencing, favors, informants, debt, bounties, and a heat/wanted/law-response
loop that reuses dagger-sim debt and bounty state (catalogue 10.5); and cybernetic implants
with augmentation slots, clinics/street surgeons, maintenance, overclocking, legality, and
hacking vulnerability that reuses the hacking and heat systems (catalogue 10.6); and fixers,
runner contracts, handlers, data delivery, payouts, double-crosses, blackmail, leaks, and
asset extraction (catalogue 10.4).
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
    LockableComponent,
    PortableComponent,
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
from ..core.ecs import (
    entity_name as _name,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from ..prompts import ComponentPromptContext
from .colonysim import ResourceStackComponent
from .daggersim import BountyComponent, BountyPostedEvent, DebtComponent
from .voidsim import DroneComponent

SCRIP_RESOURCE = "scrip"
SECONDS_PER_HOUR = 60 * 60


def _payload_entity_id(command: SubmittedCommand, *keys: str):
    for key in keys:
        if key in command.payload:
            return parse_entity_id(command.payload.get(key))
    return None


def _can_handle_target_component(
    ctx: HandlerContext,
    command: SubmittedCommand,
    component_type: type[Component],
    *keys: str,
) -> bool:
    payload = command.payload
    if any(key != "target_id" and key in payload for key in keys):
        return True
    target_id = _payload_entity_id(command, *keys)
    if target_id is None or not ctx.world.has_entity(target_id):
        return any(key in payload for key in keys)
    character_id = parse_entity_id(command.character_id)
    if character_id is None or not ctx.world.has_entity(character_id):
        return True
    if target_id not in reachable_ids(ctx.world, ctx.entity(character_id)):
        return True
    return ctx.entity(target_id).has_component(component_type)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        tags: list[str] = []
        if ctx.entity.has_component(SecurityZoneComponent):
            zone = ctx.entity.get_component(SecurityZoneComponent)
            tags.append(f"clearance {zone.clearance_required}")
            if zone.alarm_raised:
                tags.append("ALARM")
        if ctx.entity.has_component(PublicAccessComponent):
            tags.append("public")
        if ctx.entity.has_component(RestrictedAreaComponent):
            tags.append("restricted")
        if (
            ctx.target is not None
            and ctx.target.has_relationship(InsideZone, ctx.entity.id)
            and ctx.can_view_private_state
        ):
            tags.append("you are inside")
        suffix = f" ({', '.join(tags)})" if tags else ""
        return (f"Site {_name(ctx.entity)}: {self.site_type}{suffix}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or (self.clearance <= 0 and not self.passes):
            return ()
        passes = f", passes: {', '.join(self.passes)}" if self.passes else ""
        return (f"Security clearance: level {self.clearance}{passes}.",)


@dataclass(frozen=True)
class CheckpointComponent(Component):
    """A manned gate. ``zone_tag`` matches an :class:`AccessLevelComponent` pass."""

    clearance_required: int = 1
    bribe_cost: int = 0
    zone_tag: str = ""
    alerted: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "alerted" if self.alerted else "calm"
        bribe = f", bribe {self.bribe_cost} scrip" if self.bribe_cost > 0 else ""
        return (
            f"Checkpoint {_name(ctx.entity)}: clearance {self.clearance_required}, "
            f"{state}{bribe}.",
        )


@dataclass(frozen=True)
class SafehouseComponent(Component):
    claimed_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "unclaimed" if self.claimed_by is None else "claimed"
        return (f"Safehouse {_name(ctx.entity)}: {state}.",)


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
    # Contains edges to a removed entity are cascaded away by Relics, so item_id is live.
    for _edge, item_id in character.get_relationships(Contains):
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
    command_type = "bribe"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        return _can_handle_target_component(
            ctx, command, CheckpointComponent, "target_id", "checkpoint_id"
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        checkpoint, error = _reachable_component(
            ctx,
            character_id,
            _payload_entity_id(command, "target_id", "checkpoint_id"),
            CheckpointComponent,
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
    command_type = "sneak"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        return _can_handle_target_component(
            ctx, command, CheckpointComponent, "target_id", "checkpoint_id"
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        checkpoint, error = _reachable_component(
            ctx,
            character_id,
            _payload_entity_id(command, "target_id", "checkpoint_id"),
            CheckpointComponent,
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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        states: list[str] = []
        if not self.powered:
            states.append("unpowered")
        if self.disabled:
            states.append("disabled")
        if (
            ctx.entity.has_component(CameraComponent)
            and ctx.entity.get_component(CameraComponent).looped
        ):
            states.append("looped")
        if ctx.entity.has_component(SurveillanceCoverageComponent) and not states:
            states.append("watching")
        if ctx.entity.has_component(HackableComponent):
            hack = ctx.entity.get_component(HackableComponent)
            if hack.breached:
                states.append(f"breached/{hack.privilege}")
            else:
                states.append(f"security {hack.security}")
            if hack.backdoored:
                states.append("backdoored")
        suffix = f" ({', '.join(states)})" if states else ""
        return (f"Device {_name(ctx.entity)}: {self.device_type}{suffix}.",)


@dataclass(frozen=True)
class CameraComponent(Component):
    """Camera-specific state. ``looped`` feeds a fake signal so it records nothing."""

    looped: bool = False


@dataclass(frozen=True)
class SurveillanceCoverageComponent(Component):
    """Marks a device as actively watching its room and able to record evidence."""

    coverage: float = 1.0


@dataclass(frozen=True)
class RecordedEvidenceComponent(Component):
    subject_id: str
    device_id: str
    device_type: str = "camera"
    wiped: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.wiped:
            return ()
        return (f"Recorded evidence: {_name(ctx.entity)} ({self.device_type}).",)


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
    command_type = "inspect"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        return _can_handle_target_component(
            ctx, command, DeviceComponent, "target_id", "device_id"
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_device(
            ctx, character_id, _payload_entity_id(command, "target_id", "device_id")
        )
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
        if drone.active:
            return rejected("drone is already deployed")
        replace_component(device, replace(drone, active=True))
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


# --- Components (catalogue 10.3: hacking, credentials, intrusion) --------------------


@dataclass(frozen=True)
class HackableComponent(Component):
    """A device that can be breached. ``owner`` matches a credential's ``target_owner``."""

    security: int = 1
    owner: str = ""
    breached: bool = False
    privilege: str = "user"
    backdoored: bool = False


@dataclass(frozen=True)
class ExploitComponent(Component):
    """A hacking tool carried in inventory. ``power`` is compared against security."""

    power: int = 1
    single_use: bool = False


@dataclass(frozen=True)
class CredentialComponent(Component):
    """A stored credential/access token that opens devices owned by ``target_owner``."""

    target_owner: str = ""
    privilege: str = "user"


@dataclass(frozen=True)
class DataPayloadComponent(Component):
    name: str = "data cache"
    sensitive: bool = False
    exfiltrated: bool = False


@dataclass(frozen=True)
class TraceTimerComponent(Component):
    """A counter-intrusion trace closing in on the hacker; expiry raises the alarm."""

    remaining: float = 0.0
    source_id: str = ""
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Counter-intrusion trace closing in: {self.remaining:g}s left.",)


# --- Events (catalogue 10.3) ---------------------------------------------------------


class NetworkScannedEvent(DomainEvent):
    character_id: str
    device_id: str
    security: int
    breached: bool


class NetworkTracedEvent(DomainEvent):
    character_id: str
    device_id: str
    node_count: int


class TerminalAccessedEvent(DomainEvent):
    character_id: str
    device_id: str


class CredentialUsedEvent(DomainEvent):
    character_id: str
    device_id: str
    privilege: str


class HackSucceededEvent(DomainEvent):
    character_id: str
    device_id: str


class HackFailedEvent(DomainEvent):
    character_id: str
    device_id: str


class BackdoorInstalledEvent(DomainEvent):
    character_id: str
    device_id: str


class PrivilegesEscalatedEvent(DomainEvent):
    character_id: str
    device_id: str
    privilege: str


class TraceStartedEvent(DomainEvent):
    character_id: str
    device_id: str
    seconds: float


class TraceEvadedEvent(DomainEvent):
    character_id: str


class IdentitySpoofedEvent(DomainEvent):
    character_id: str
    seconds: float


class DataExfiltratedEvent(DomainEvent):
    character_id: str
    device_id: str
    data_id: str
    name: str


class SystemSabotagedEvent(DomainEvent):
    character_id: str
    device_id: str


class DoorUnlockedEvent(DomainEvent):
    character_id: str
    device_id: str


class AlarmRaisedEvent(DomainEvent):
    character_id: str
    source: str = "intrusion"


TRACE_SECONDS = 3600.0
SPOOF_EXTRA_SECONDS = 3600.0


# --- Hacking helpers -----------------------------------------------------------------


def _best_exploit(character: Entity, world: World) -> tuple[int, Entity | None]:
    best_power = 0
    best_item: Entity | None = None
    for edge, item_id in character.get_relationships(Contains):
        if edge.mode != ContainmentMode.INVENTORY or not world.has_entity(item_id):
            continue
        item = world.get_entity(item_id)
        if not item.has_component(ExploitComponent):
            continue
        power = item.get_component(ExploitComponent).power
        if power > best_power:
            best_power = power
            best_item = item
    return best_power, best_item


def _matching_credential(character: Entity, world: World, owner: str) -> Entity | None:
    for edge, item_id in character.get_relationships(Contains):
        if edge.mode != ContainmentMode.INVENTORY or not world.has_entity(item_id):
            continue
        item = world.get_entity(item_id)
        if (
            item.has_component(CredentialComponent)
            and item.get_component(CredentialComponent).target_owner == owner
        ):
            return item
    return None


def _raise_local_alarm(world: World, character_id: EntityId) -> None:
    character = world.get_entity(character_id)
    # reachable_ids() only returns ids of live entities, so no existence re-check needed.
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(SecurityZoneComponent):
            zone = entity.get_component(SecurityZoneComponent)
            if not zone.alarm_raised:
                replace_component(entity, replace(zone, alarm_raised=True))


def _start_trace(character: Entity, world: World, epoch: int, device_id: EntityId) -> DomainEvent:
    replace_component(
        character,
        TraceTimerComponent(
            remaining=TRACE_SECONDS,
            source_id=str(device_id),
            last_updated_epoch=epoch,
        ),
    )
    return TraceStartedEvent(
        **_event_base(
            epoch,
            visibility=EventVisibility.PRIVATE,
            actor_id=str(character.id),
            room_id=_room_id(world, character.id),
            target_ids=(str(device_id),),
            character_id=str(character.id),
            device_id=str(device_id),
            seconds=TRACE_SECONDS,
        )
    )


# --- Consequences (catalogue 10.3 systems) -------------------------------------------


class TraceTimerConsequence:
    """Counter-intrusion: an active trace counts down and trips the alarm on expiry."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in (
            world.query()
            .with_all([CharacterComponent, TraceTimerComponent])
            .with_none([DeadComponent])
            .execute_entities()
        ):
            timer = character.get_component(TraceTimerComponent)
            elapsed = max(0, epoch - timer.last_updated_epoch)
            if elapsed <= 0:
                continue
            remaining = timer.remaining - elapsed
            if remaining > 0:
                replace_component(
                    character, replace(timer, remaining=remaining, last_updated_epoch=epoch)
                )
                continue
            character.remove_component(TraceTimerComponent)
            _raise_local_alarm(world, character.id)
            events.append(
                AlarmRaisedEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character.id),
                        room_id=_room_id(world, character.id),
                        character_id=str(character.id),
                        source="trace",
                    )
                )
            )
        return events


# --- Handlers (catalogue 10.3 actions) -----------------------------------------------


class ScanNetworkHandler:
    command_type = "scan-network"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        hack = device.get_component(HackableComponent)
        return ok(
            NetworkScannedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                    security=hack.security,
                    breached=hack.breached,
                )
            )
        )


class TraceNetworkHandler:
    command_type = "trace-network"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        room_id = container_of(device)
        node_count = 0
        if room_id is not None and ctx.world.has_entity(room_id):
            for _edge, sibling_id in ctx.world.get_entity(room_id).get_relationships(Contains):
                if ctx.world.has_entity(sibling_id) and ctx.world.get_entity(
                    sibling_id
                ).has_component(HackableComponent):
                    node_count += 1
        return ok(
            NetworkTracedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                    node_count=node_count,
                )
            )
        )


class RunExploitHandler:
    command_type = "run-exploit"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        hack = device.get_component(HackableComponent)
        if hack.breached:
            return rejected("system is already breached")
        character = ctx.entity(character_id)
        power, exploit_item = _best_exploit(character, ctx.world)
        if hack.backdoored or power >= hack.security:
            replace_component(device, replace(hack, breached=True))
            if exploit_item is not None and exploit_item.get_component(ExploitComponent).single_use:
                parent_id = container_of(exploit_item)
                if parent_id is not None and ctx.world.has_entity(parent_id):
                    ctx.world.get_entity(parent_id).remove_relationship(Contains, exploit_item.id)
                ctx.world.remove(exploit_item.id)
            events: list[DomainEvent] = [
                HackSucceededEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(device.id),),
                        character_id=str(character_id),
                        device_id=str(device.id),
                    )
                )
            ]
            if not hack.backdoored:
                events.append(_start_trace(character, ctx.world, ctx.epoch, device.id))
            return ok(*events)
        _raise_local_alarm(ctx.world, character_id)
        return ok(
            HackFailedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                )
            ),
            AlarmRaisedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    source="failed hack",
                )
            ),
        )


class UseCredentialHandler:
    command_type = "use-credential"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        hack = device.get_component(HackableComponent)
        character = ctx.entity(character_id)
        credential = _matching_credential(character, ctx.world, hack.owner)
        if credential is None:
            return rejected("no credential matches this system")
        privilege = credential.get_component(CredentialComponent).privilege
        replace_component(device, replace(hack, breached=True, privilege=privilege))
        return ok(
            CredentialUsedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                    privilege=privilege,
                )
            )
        )


class AccessTerminalHandler:
    command_type = "access-terminal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a terminal")
        hack = device.get_component(HackableComponent)
        if not hack.breached and not hack.backdoored:
            return rejected("terminal is locked; breach it first")
        return ok(
            TerminalAccessedEvent(
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


class EscalatePrivilegesHandler:
    command_type = "escalate-privileges"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        hack = device.get_component(HackableComponent)
        if not hack.breached and not hack.backdoored:
            return rejected("breach the system first")
        if hack.privilege == "admin":
            return rejected("already running as admin")
        replace_component(device, replace(hack, privilege="admin"))
        return ok(
            PrivilegesEscalatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id),),
                    character_id=str(character_id),
                    device_id=str(device.id),
                    privilege="admin",
                )
            )
        )


class InstallBackdoorHandler:
    command_type = "install-backdoor"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        hack = device.get_component(HackableComponent)
        if not hack.breached:
            return rejected("breach the system first")
        if hack.backdoored:
            return rejected("backdoor is already installed")
        replace_component(device, replace(hack, backdoored=True))
        return ok(
            BackdoorInstalledEvent(
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


class ExfiltrateDataHandler:
    command_type = "exfiltrate-data"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        hack = device.get_component(HackableComponent)
        if not hack.breached and not hack.backdoored:
            return rejected("breach the system first")
        if not device.has_component(DataPayloadComponent):
            return rejected("target holds no data")
        payload = device.get_component(DataPayloadComponent)
        if payload.exfiltrated:
            return rejected("data has already been exfiltrated")
        if payload.sensitive and hack.privilege != "admin":
            return rejected("sensitive data needs admin privileges")
        replace_component(device, replace(payload, exfiltrated=True))
        character = ctx.entity(character_id)
        data_item = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=payload.name, kind="data"),
                DataPayloadComponent(name=payload.name, sensitive=payload.sensitive),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), data_item.id)
        return ok(
            DataExfiltratedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(device.id), str(data_item.id)),
                    character_id=str(character_id),
                    device_id=str(device.id),
                    data_id=str(data_item.id),
                    name=payload.name,
                )
            )
        )


class SabotageSystemHandler:
    command_type = "sabotage-system"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HackableComponent
        )
        if device is None:
            return rejected(error if error else "target is not a network device")
        hack = device.get_component(HackableComponent)
        if not hack.breached and not hack.backdoored:
            return rejected("breach the system first")
        if device.has_component(DeviceComponent):
            dev = device.get_component(DeviceComponent)
            if dev.disabled:
                return rejected("system is already sabotaged")
            replace_component(device, replace(dev, disabled=True))
        return ok(
            SystemSabotagedEvent(
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


class UnlockDoorHandler:
    command_type = "unlock"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        return _can_handle_target_component(
            ctx, command, HackableComponent, "target_id", "device_id"
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        device, error = _reachable_component(
            ctx,
            character_id,
            _payload_entity_id(command, "target_id", "device_id"),
            LockableComponent,
        )
        if device is None:
            return rejected(error if error else "target has no electronic lock")
        if not device.has_component(HackableComponent):
            return rejected("target is not a network device")
        hack = device.get_component(HackableComponent)
        if not hack.breached and not hack.backdoored:
            return rejected("breach the system first")
        lock = device.get_component(LockableComponent)
        if not lock.locked:
            return rejected("door is already unlocked")
        replace_component(device, replace(lock, locked=False))
        return ok(
            DoorUnlockedEvent(
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


class EvadeTraceHandler:
    command_type = "evade-trace"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if not character.has_component(TraceTimerComponent):
            return rejected("no active trace to evade")
        character.remove_component(TraceTimerComponent)
        return ok(
            TraceEvadedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                )
            )
        )


class SpoofIdentityHandler:
    command_type = "spoof-identity"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if not character.has_component(TraceTimerComponent):
            return rejected("no active trace to spoof")
        timer = character.get_component(TraceTimerComponent)
        replace_component(
            character,
            replace(
                timer,
                remaining=timer.remaining + SPOOF_EXTRA_SECONDS,
                last_updated_epoch=ctx.epoch,
            ),
        )
        return ok(
            IdentitySpoofedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    seconds=SPOOF_EXTRA_SECONDS,
                )
            )
        )


# --- Components (catalogue 10.5: street economy, reputation, heat, wanted) -----------


@dataclass(frozen=True)
class BlackMarketComponent(Component):
    """A street vendor that sells one contraband line and buys it back."""

    price: int = 20
    contraband_name: str = "contraband"
    contraband_value: int = 10
    contraband_heat: float = 2.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (
            f"Black market {_name(ctx.entity)}: {self.contraband_name} "
            f"for {self.price} scrip.",
        )


@dataclass(frozen=True)
class DataBrokerComponent(Component):
    """A fence that buys exfiltrated data payloads for scrip."""

    rate: int = 50

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Data broker {_name(ctx.entity)} buying data here.",)


@dataclass(frozen=True)
class ContrabandComponent(Component):
    value: int = 10
    heat: float = 2.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Contraband: {_name(ctx.entity)}.",)


@dataclass(frozen=True)
class HeatComponent(Component):
    """Accumulated police attention on a character; decays over time."""

    amount: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or self.amount <= 0.0:
            return ()
        return (f"Police heat: {self.amount:g}.",)


@dataclass(frozen=True)
class WantedLevelComponent(Component):
    level: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Wanted level: {self.level}.",)


@dataclass(frozen=True)
class InformantComponent(Component):
    faction: str = "police"
    flip_cost: int = 30
    flipped: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "turned" if self.flipped else "available"
        return (f"Informant {_name(ctx.entity)} ({self.faction}): {state}.",)


@dataclass(frozen=True)
class OwesFavor(Edge):
    """contact -> character: the contact owes the character a callable favor."""

    reason: str = ""


# --- Events (catalogue 10.5) ---------------------------------------------------------


class ContrabandBoughtEvent(DomainEvent):
    character_id: str
    item_id: str
    price: int


class DataSoldEvent(DomainEvent):
    character_id: str
    data_id: str
    price: int


class FavorCalledEvent(DomainEvent):
    character_id: str
    contact_id: str


class DebtPaidEvent(DomainEvent):
    character_id: str
    amount: int
    remaining: int


class HeatChangedEvent(DomainEvent):
    character_id: str
    amount: float


class WantedLevelChangedEvent(DomainEvent):
    character_id: str
    level: int


class WarrantClearedEvent(DomainEvent):
    character_id: str


class InformantTurnedEvent(DomainEvent):
    character_id: str
    informant_id: str


class LawResponseEvent(DomainEvent):
    character_id: str
    level: int


WANTED_THRESHOLDS = (10.0, 25.0, 50.0)
HEAT_DECAY_PER_HOUR = 1.0
HIDE_HEAT_REDUCTION = 8.0
CLEAR_WARRANT_COST_PER_LEVEL = 40


# --- Street-economy helpers ----------------------------------------------------------


def _wanted_for_heat(amount: float) -> int:
    return sum(1 for threshold in WANTED_THRESHOLDS if amount >= threshold)


def _heat_component(character: Entity) -> HeatComponent:
    if character.has_component(HeatComponent):
        return character.get_component(HeatComponent)
    return HeatComponent()


def _add_heat(character: Entity, epoch: int, delta: float) -> float:
    heat = _heat_component(character)
    amount = max(0.0, heat.amount + delta)
    replace_component(character, HeatComponent(amount=amount, last_updated_epoch=epoch))
    return amount


def _scrip_stack(character: Entity, world: World) -> Entity | None:
    for edge, item_id in character.get_relationships(Contains):
        if edge.mode != ContainmentMode.INVENTORY or not world.has_entity(item_id):
            continue
        item = world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == SCRIP_RESOURCE
        ):
            return item
    return None


def _add_scrip(character: Entity, world: World, amount: int) -> None:
    if amount <= 0:
        return
    existing = _scrip_stack(character, world)
    if existing is not None:
        stack = existing.get_component(ResourceStackComponent)
        total = stack.quantity + amount
        replace_component(existing, replace(stack, quantity=total))
        replace_component(
            existing, IdentityComponent(name=f"{SCRIP_RESOURCE} x{total}", kind="resource")
        )
        return
    item = spawn_entity(
        world,
        [
            IdentityComponent(name=f"{SCRIP_RESOURCE} x{amount}", kind="resource"),
            ResourceStackComponent(resource_type=SCRIP_RESOURCE, quantity=amount),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)


def _inventory_item(character: Entity, world: World, target_id, component):
    parsed = parse_entity_id(target_id)
    if parsed is None or not world.has_entity(parsed):
        return None
    if not character.has_relationship(Contains, parsed):
        return None
    item = world.get_entity(parsed)
    return item if item.has_component(component) else None


def _remove_item(world: World, item_id: EntityId) -> None:
    entity = world.get_entity(item_id)
    parent_id = container_of(entity)
    if parent_id is not None and world.has_entity(parent_id):
        world.get_entity(parent_id).remove_relationship(Contains, item_id)
    world.remove(item_id)


# --- Consequences (catalogue 10.5 systems) -------------------------------------------


class HeatConsequence:
    """Decays heat over time and recomputes the wanted level, triggering law response."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in (
            world.query()
            .with_all([CharacterComponent, HeatComponent])
            .with_none([DeadComponent])
            .execute_entities()
        ):
            heat = character.get_component(HeatComponent)
            elapsed = max(0, epoch - heat.last_updated_epoch)
            amount = heat.amount
            if elapsed > 0:
                amount = max(0.0, heat.amount - HEAT_DECAY_PER_HOUR * (elapsed / SECONDS_PER_HOUR))
                replace_component(
                    character, HeatComponent(amount=amount, last_updated_epoch=epoch)
                )
            old_level = (
                character.get_component(WantedLevelComponent).level
                if character.has_component(WantedLevelComponent)
                else 0
            )
            new_level = _wanted_for_heat(amount)
            if new_level == old_level:
                continue
            if new_level > 0:
                replace_component(character, WantedLevelComponent(level=new_level))
            else:
                # Reaching here means new_level == 0 != old_level, so a non-zero
                # WantedLevelComponent is always present to remove.
                character.remove_component(WantedLevelComponent)
            events.append(
                WantedLevelChangedEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character.id),
                        room_id=_room_id(world, character.id),
                        character_id=str(character.id),
                        level=new_level,
                    )
                )
            )
            if new_level > old_level:
                _raise_local_alarm(world, character.id)
                events.append(
                    LawResponseEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            character_id=str(character.id),
                            level=new_level,
                        )
                    )
                )
        return events


# --- Handlers (catalogue 10.5 actions) -----------------------------------------------


class BuyContrabandHandler:
    command_type = "buy-contraband"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        vendor, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), BlackMarketComponent
        )
        if vendor is None:
            return rejected(error if error else "target is not a black-market vendor")
        market = vendor.get_component(BlackMarketComponent)
        character = ctx.entity(character_id)
        if not _spend_scrip(character, ctx.world, market.price):
            return rejected("not enough scrip for the contraband")
        item = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=market.contraband_name, kind="contraband"),
                ContrabandComponent(value=market.contraband_value, heat=market.contraband_heat),
                PortableComponent(can_pick_up=True),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
        heat = _add_heat(character, ctx.epoch, market.contraband_heat)
        return ok(
            ContrabandBoughtEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(vendor.id), str(item.id)),
                    character_id=str(character_id),
                    item_id=str(item.id),
                    price=market.price,
                )
            ),
            HeatChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    amount=heat,
                )
            ),
        )


class SellDataHandler:
    command_type = "sell-data"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        broker, error = _reachable_component(
            ctx, character_id, command.payload.get("broker_id"), DataBrokerComponent
        )
        if broker is None:
            return rejected(error if error else "target is not a data broker")
        character = ctx.entity(character_id)
        data = _inventory_item(
            character, ctx.world, command.payload.get("data_id"), DataPayloadComponent
        )
        if data is None:
            return rejected("you are not carrying that data")
        payload = data.get_component(DataPayloadComponent)
        price = broker.get_component(DataBrokerComponent).rate * (2 if payload.sensitive else 1)
        data_id = str(data.id)
        _remove_item(ctx.world, data.id)
        _add_scrip(character, ctx.world, price)
        return ok(
            DataSoldEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(broker.id),),
                    character_id=str(character_id),
                    data_id=data_id,
                    price=price,
                )
            )
        )


class CallFavorHandler:
    command_type = "call-favor"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contact, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CharacterComponent
        )
        if contact is None:
            return rejected(error if error else "target is not a contact")
        if not contact.has_relationship(OwesFavor, character_id):
            return rejected("they owe you no favor")
        contact.remove_relationship(OwesFavor, character_id)
        return ok(
            FavorCalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(contact.id),),
                    character_id=str(character_id),
                    contact_id=str(contact.id),
                )
            )
        )


class PayDebtHandler:
    command_type = "pay-debt"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if not character.has_component(DebtComponent):
            return rejected("you have no debt")
        debt = character.get_component(DebtComponent)
        scrip = _scrip_stack(character, ctx.world)
        available = scrip.get_component(ResourceStackComponent).quantity if scrip else 0
        if available <= 0:
            return rejected("not enough scrip to pay the debt")
        payment = min(available, debt.amount)
        if not _spend_scrip(character, ctx.world, payment):
            return rejected("not enough scrip to pay the debt")
        remaining = debt.amount - payment
        if remaining > 0:
            replace_component(character, replace(debt, amount=remaining))
        else:
            character.remove_component(DebtComponent)
        return ok(
            DebtPaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    amount=payment,
                    remaining=remaining,
                )
            )
        )


class PostBountyHandler:
    command_type = "post-bounty"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        target, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CharacterComponent
        )
        if target is None:
            return rejected(error if error else "target is not a person")
        try:
            amount = int(command.payload.get("amount", 0))
        except (TypeError, ValueError):
            return rejected("invalid bounty amount")
        if amount <= 0:
            return rejected("bounty amount must be positive")
        character = ctx.entity(character_id)
        if not _spend_scrip(character, ctx.world, amount):
            return rejected("not enough scrip to post the bounty")
        existing = (
            target.get_component(BountyComponent).amount
            if target.has_component(BountyComponent)
            else 0
        )
        region = _district_name(ctx.world, target.id)
        replace_component(target, BountyComponent(amount=existing + amount, region_id=region))
        # Reuse dagger-sim's bounty event/state; a street bounty is the same record placed
        # deliberately by a runner rather than generated by a crime, so crime_id is empty.
        return ok(
            BountyPostedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target.id),),
                    crime_id="",
                    amount=amount,
                )
            )
        )


class TurnInformantHandler:
    command_type = "turn-informant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        informant, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), InformantComponent
        )
        if informant is None:
            return rejected(error if error else "target is not an informant")
        component = informant.get_component(InformantComponent)
        if component.flipped:
            return rejected("informant is already turned")
        character = ctx.entity(character_id)
        if not _spend_scrip(character, ctx.world, component.flip_cost):
            return rejected("not enough scrip to turn the informant")
        replace_component(informant, replace(component, flipped=True))
        return ok(
            InformantTurnedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(informant.id),),
                    character_id=str(character_id),
                    informant_id=str(informant.id),
                )
            )
        )


class HideFromLawHandler:
    command_type = "hide-from-law"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if _heat_component(character).amount <= 0.0:
            return rejected("you are not being hunted")
        if not _in_claimed_safehouse(ctx.world, character_id):
            return rejected("lay low in a safehouse you have claimed")
        heat = _add_heat(character, ctx.epoch, -HIDE_HEAT_REDUCTION)
        return ok(
            HeatChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    amount=heat,
                )
            )
        )


class ClearWarrantHandler:
    command_type = "clear-warrant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if not character.has_component(WantedLevelComponent):
            return rejected("you have no warrant")
        level = character.get_component(WantedLevelComponent).level
        cost = level * CLEAR_WARRANT_COST_PER_LEVEL
        if not _spend_scrip(character, ctx.world, cost):
            return rejected("not enough scrip to clear the warrant")
        character.remove_component(WantedLevelComponent)
        replace_component(character, HeatComponent(amount=0.0, last_updated_epoch=ctx.epoch))
        return ok(
            WarrantClearedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                )
            ),
            WantedLevelChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    level=0,
                )
            ),
        )


def _in_claimed_safehouse(world: World, character_id: EntityId) -> bool:
    character = world.get_entity(character_id)
    # reachable_ids() only returns ids of live entities, so no existence re-check needed.
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(SafehouseComponent):
            if entity.get_component(SafehouseComponent).claimed_by == str(character_id):
                return True
    return False


# --- Components (catalogue 10.6: cybernetics, implants, tradeoffs) --------------------


@dataclass(frozen=True)
class ImplantComponent(Component):
    """A cybernetic implant. Each type defines its own tradeoff mix (catalogue 10.6)."""

    implant_type: str = "implant"
    slot: str = "body"
    slot_cost: int = 1
    power_draw: float = 1.0
    legal: bool = True
    install_heat: float = 0.0
    maintenance_interval: float = 0.0
    side_effect: str = ""
    active: bool = True
    overclocked: bool = False
    serviced_epoch: int = 0
    maintenance_due_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if (
            ctx.target is not None
            and ctx.target.has_relationship(HasImplant, ctx.entity.id)
            and ctx.can_view_private_state
        ):
            tags = [self.slot]
            if not self.active:
                tags.append("offline")
            if self.overclocked:
                tags.append("overclocked")
            if not self.legal:
                tags.append("illegal")
            return (f"Implant {_name(ctx.entity)}: {self.implant_type} ({', '.join(tags)}).",)
        legality = "legal" if self.legal else "ILLEGAL"
        return (f"Implant for sale: {_name(ctx.entity)} ({self.implant_type}, {legality}).",)


@dataclass(frozen=True)
class AugmentationSlotsComponent(Component):
    capacity: int = 3


@dataclass(frozen=True)
class ClinicComponent(Component):
    """A clinic or street surgeon. Licensed clinics refuse illegal implants."""

    licensed: bool = True
    install_cost: int = 50
    service_cost: int = 20

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        kind = "Licensed clinic" if self.licensed else "Street surgeon"
        return (f"{kind} {_name(ctx.entity)}: install {self.install_cost} scrip.",)


@dataclass(frozen=True)
class HasImplant(Edge):
    """character -> implant entity installed in their body."""

    slot: str = "body"
    installed_epoch: int = 0


DEFAULT_AUG_CAPACITY = 3
OVERCLOCK_POWER_BONUS = 1.0


# --- Events (catalogue 10.6) ---------------------------------------------------------


class ImplantInstalledEvent(DomainEvent):
    character_id: str
    implant_id: str
    implant_type: str


class ImplantRemovedEvent(DomainEvent):
    character_id: str
    implant_id: str


class ImplantServicedEvent(DomainEvent):
    character_id: str
    implant_id: str


class ImplantOverclockedEvent(DomainEvent):
    character_id: str
    implant_id: str


class ImplantDisabledEvent(DomainEvent):
    character_id: str
    implant_id: str


class ImplantScannedEvent(DomainEvent):
    character_id: str
    subject_id: str
    implant_count: int


class ImplantLicensedEvent(DomainEvent):
    character_id: str
    implant_id: str


class ImplantExploitedEvent(DomainEvent):
    character_id: str
    subject_id: str
    implant_id: str


class SideEffectTriggeredEvent(DomainEvent):
    character_id: str
    implant_id: str
    side_effect: str


# --- Cybernetics helpers -------------------------------------------------------------


def _installed_implants(character: Entity, world: World) -> list[tuple[object, Entity]]:
    found: list[tuple[object, Entity]] = []
    for edge, implant_id in character.get_relationships(HasImplant):
        if world.has_entity(implant_id) and world.get_entity(implant_id).has_component(
            ImplantComponent
        ):
            found.append((edge, world.get_entity(implant_id)))
    return found


def _own_implant(character: Entity, world: World, implant_id) -> Entity | None:
    parsed = parse_entity_id(implant_id)
    if parsed is None or not world.has_entity(parsed):
        return None
    if not character.has_relationship(HasImplant, parsed):
        return None
    implant = world.get_entity(parsed)
    return implant if implant.has_component(ImplantComponent) else None


def _augmentation_capacity(character: Entity) -> int:
    if character.has_component(AugmentationSlotsComponent):
        return character.get_component(AugmentationSlotsComponent).capacity
    return DEFAULT_AUG_CAPACITY


# --- Consequences (catalogue 10.6 systems) -------------------------------------------


class ImplantMaintenanceConsequence:
    """Neglected active implants periodically misfire, triggering their side effect."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in (
            world.query()
            .with_all([CharacterComponent])
            .with_none([DeadComponent, SuspendedComponent])
            .execute_entities()
        ):
            for _edge, implant in _installed_implants(character, world):
                comp = implant.get_component(ImplantComponent)
                if not comp.active or comp.maintenance_interval <= 0:
                    continue
                if epoch < comp.maintenance_due_epoch:
                    continue
                replace_component(
                    implant,
                    replace(comp, maintenance_due_epoch=epoch + int(comp.maintenance_interval)),
                )
                if not comp.side_effect:
                    continue
                events.append(
                    SideEffectTriggeredEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            target_ids=(str(implant.id),),
                            character_id=str(character.id),
                            implant_id=str(implant.id),
                            side_effect=comp.side_effect,
                        )
                    )
                )
        return events


# --- Handlers (catalogue 10.6 actions) -----------------------------------------------


class InstallImplantHandler:
    command_type = "install-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        clinic, error = _reachable_component(
            ctx, character_id, command.payload.get("clinic_id"), ClinicComponent
        )
        if clinic is None:
            return rejected(error if error else "target is not a clinic")
        character = ctx.entity(character_id)
        item = _inventory_item(
            character, ctx.world, command.payload.get("implant_id"), ImplantComponent
        )
        if item is None:
            return rejected("you are not carrying that implant")
        implant = item.get_component(ImplantComponent)
        used = sum(
            impl.get_component(ImplantComponent).slot_cost
            for _e, impl in _installed_implants(character, ctx.world)
        )
        if used + implant.slot_cost > _augmentation_capacity(character):
            return rejected("no free augmentation slots")
        clinic_comp = clinic.get_component(ClinicComponent)
        if not implant.legal and clinic_comp.licensed:
            return rejected("a licensed clinic will not fit an illegal implant")
        if not _spend_scrip(character, ctx.world, clinic_comp.install_cost):
            return rejected("not enough scrip for the procedure")
        character.remove_relationship(Contains, item.id)
        character.add_relationship(
            HasImplant(slot=implant.slot, installed_epoch=ctx.epoch), item.id
        )
        replace_component(
            item,
            replace(
                implant,
                active=True,
                serviced_epoch=ctx.epoch,
                maintenance_due_epoch=ctx.epoch + int(implant.maintenance_interval),
            ),
        )
        events: list[DomainEvent] = [
            ImplantInstalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item.id), str(clinic.id)),
                    character_id=str(character_id),
                    implant_id=str(item.id),
                    implant_type=implant.implant_type,
                )
            )
        ]
        if not implant.legal and not clinic_comp.licensed and implant.install_heat > 0:
            heat = _add_heat(character, ctx.epoch, implant.install_heat)
            events.append(
                HeatChangedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        character_id=str(character_id),
                        amount=heat,
                    )
                )
            )
        return ok(*events)


class RemoveImplantHandler:
    command_type = "remove-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        implant = _own_implant(character, ctx.world, command.payload.get("implant_id"))
        if implant is None:
            return rejected("you have no such implant")
        character.remove_relationship(HasImplant, implant.id)
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), implant.id)
        return ok(
            ImplantRemovedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(implant.id),),
                    character_id=str(character_id),
                    implant_id=str(implant.id),
                )
            )
        )


class ServiceImplantHandler:
    command_type = "service-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        clinic, error = _reachable_component(
            ctx, character_id, command.payload.get("clinic_id"), ClinicComponent
        )
        if clinic is None:
            return rejected(error if error else "target is not a clinic")
        character = ctx.entity(character_id)
        implant = _own_implant(character, ctx.world, command.payload.get("implant_id"))
        if implant is None:
            return rejected("you have no such implant")
        comp = implant.get_component(ImplantComponent)
        if comp.maintenance_interval <= 0:
            return rejected("this implant needs no maintenance")
        service_cost = clinic.get_component(ClinicComponent).service_cost
        if not _spend_scrip(character, ctx.world, service_cost):
            return rejected("not enough scrip for the service")
        replace_component(
            implant,
            replace(
                comp,
                serviced_epoch=ctx.epoch,
                maintenance_due_epoch=ctx.epoch + int(comp.maintenance_interval),
            ),
        )
        return ok(
            ImplantServicedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(implant.id),),
                    character_id=str(character_id),
                    implant_id=str(implant.id),
                )
            )
        )


class OverclockImplantHandler:
    command_type = "overclock-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        implant = _own_implant(character, ctx.world, command.payload.get("implant_id"))
        if implant is None:
            return rejected("you have no such implant")
        comp = implant.get_component(ImplantComponent)
        if comp.overclocked:
            return rejected("implant is already overclocked")
        interval = comp.maintenance_interval / 2 if comp.maintenance_interval > 0 else 0.0
        replace_component(
            implant,
            replace(
                comp,
                overclocked=True,
                power_draw=comp.power_draw + OVERCLOCK_POWER_BONUS,
                maintenance_interval=interval,
                maintenance_due_epoch=(
                    ctx.epoch + int(interval) if interval > 0 else comp.maintenance_due_epoch
                ),
            ),
        )
        return ok(
            ImplantOverclockedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(implant.id),),
                    character_id=str(character_id),
                    implant_id=str(implant.id),
                )
            )
        )


class DisableImplantHandler:
    command_type = "disable-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        implant = _own_implant(character, ctx.world, command.payload.get("implant_id"))
        if implant is None:
            return rejected("you have no such implant")
        comp = implant.get_component(ImplantComponent)
        if not comp.active:
            return rejected("implant is already disabled")
        replace_component(implant, replace(comp, active=False))
        return ok(
            ImplantDisabledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(implant.id),),
                    character_id=str(character_id),
                    implant_id=str(implant.id),
                )
            )
        )


class LicenseImplantHandler:
    command_type = "license-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        implant = _own_implant(character, ctx.world, command.payload.get("implant_id"))
        if implant is None:
            return rejected("you have no such implant")
        comp = implant.get_component(ImplantComponent)
        if comp.legal:
            return rejected("implant is already licensed")
        try:
            fee = int(command.payload.get("fee", comp.install_heat * 10))
        except (TypeError, ValueError):
            fee = 0
        fee = max(0, fee)
        if not _spend_scrip(character, ctx.world, fee):
            return rejected("not enough scrip for the license fee")
        replace_component(implant, replace(comp, legal=True))
        return ok(
            ImplantLicensedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(implant.id),),
                    character_id=str(character_id),
                    implant_id=str(implant.id),
                )
            )
        )


class ScanImplantHandler:
    command_type = "scan-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        subject, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CharacterComponent
        )
        if subject is None:
            return rejected(error if error else "target is not a person")
        implants = _installed_implants(subject, ctx.world)
        return ok(
            ImplantScannedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(subject.id),),
                    character_id=str(character_id),
                    subject_id=str(subject.id),
                    implant_count=len(implants),
                )
            )
        )


class ExploitImplantHandler:
    command_type = "exploit-implant"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        subject, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CharacterComponent
        )
        if subject is None:
            return rejected(error if error else "target is not a person")
        target_implant = None
        for _edge, implant in _installed_implants(subject, ctx.world):
            if implant.has_component(HackableComponent) and not implant.get_component(
                HackableComponent
            ).breached:
                target_implant = implant
                break
        if target_implant is None:
            return rejected("target has no exploitable implant")
        hack = target_implant.get_component(HackableComponent)
        character = ctx.entity(character_id)
        power, _item = _best_exploit(character, ctx.world)
        if power < hack.security:
            return ok(
                HackFailedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(target_implant.id),),
                        character_id=str(character_id),
                        device_id=str(target_implant.id),
                    )
                )
            )
        replace_component(target_implant, replace(hack, breached=True))
        implant_comp = target_implant.get_component(ImplantComponent)
        replace_component(target_implant, replace(implant_comp, active=False))
        return ok(
            ImplantExploitedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(subject.id), str(target_implant.id)),
                    character_id=str(character_id),
                    subject_id=str(subject.id),
                    implant_id=str(target_implant.id),
                )
            )
        )


# --- Components (catalogue 10.4: fixers, missions, corporate intrigue) ----------------


@dataclass(frozen=True)
class FixerComponent(Component):
    name: str = "fixer"
    burned: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "burned" if self.burned else "open for work"
        return (f"Fixer {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class HandlerComponent(Component):
    contract_id: str = ""

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Handler {_name(ctx.entity)} waiting for a hand-off.",)


@dataclass(frozen=True)
class RunnerContractComponent(Component):
    objective: str = "courier"
    payout: int = 100
    status: str = "offered"
    accepted_by: str | None = None
    double_cross: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (
            f"Contract {_name(ctx.entity)}: {self.objective}, "
            f"{self.payout} scrip ({self.status}).",
        )


@dataclass(frozen=True)
class CorporationComponent(Component):
    name: str = "corp"


@dataclass(frozen=True)
class BlackmailFileComponent(Component):
    target_id: str = ""
    leaked: bool = False
    used: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "leaked" if self.leaked else "leverage"
        return (f"Blackmail file {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class AssetExtractionComponent(Component):
    extracted: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "extracted" if self.extracted else "awaiting extraction"
        return (f"Asset {_name(ctx.entity)}: {state}.",)


DOUBLE_CROSS_HEAT = 5.0
LEAK_HEAT = 4.0


# --- Events (catalogue 10.4) ---------------------------------------------------------


class FixerJobAcceptedEvent(DomainEvent):
    character_id: str
    contract_id: str
    objective: str
    payout: int


class HandlerMetEvent(DomainEvent):
    character_id: str
    handler_id: str


class DataDeliveredEvent(DomainEvent):
    character_id: str
    contract_id: str
    data_id: str


class PayoutCollectedEvent(DomainEvent):
    character_id: str
    contract_id: str
    amount: int


class DoubleCrossRevealedEvent(DomainEvent):
    character_id: str
    contract_id: str


class ContactBurnedEvent(DomainEvent):
    character_id: str
    contact_id: str


class EvidencePlantedEvent(DomainEvent):
    character_id: str
    target_id: str
    file_id: str


class BlackmailAppliedEvent(DomainEvent):
    character_id: str
    target_id: str


class FileLeakedEvent(DomainEvent):
    character_id: str
    file_id: str


class AssetExtractedEvent(DomainEvent):
    character_id: str
    asset_id: str


# --- Handlers (catalogue 10.4 actions) -----------------------------------------------


class TakeFixerJobHandler:
    command_type = "take-fixer-job"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contract, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), RunnerContractComponent
        )
        if contract is None:
            return rejected(error if error else "target is not a contract")
        component = contract.get_component(RunnerContractComponent)
        if component.status != "offered":
            return rejected("this job is no longer available")
        replace_component(
            contract, replace(component, status="accepted", accepted_by=str(character_id))
        )
        return ok(
            FixerJobAcceptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(contract.id),),
                    character_id=str(character_id),
                    contract_id=str(contract.id),
                    objective=component.objective,
                    payout=component.payout,
                )
            )
        )


class MeetHandlerHandler:
    command_type = "meet-handler"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        handler, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), HandlerComponent
        )
        if handler is None:
            return rejected(error if error else "target is not a handler")
        return ok(
            HandlerMetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(handler.id),),
                    character_id=str(character_id),
                    handler_id=str(handler.id),
                )
            )
        )


class DeliverDataHandler:
    command_type = "deliver-data"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contract, error = _reachable_component(
            ctx, character_id, command.payload.get("contract_id"), RunnerContractComponent
        )
        if contract is None:
            return rejected(error if error else "target is not a contract")
        component = contract.get_component(RunnerContractComponent)
        if component.accepted_by != str(character_id):
            return rejected("you did not take this job")
        if component.status != "accepted":
            return rejected("this job is not awaiting delivery")
        character = ctx.entity(character_id)
        data = _inventory_item(
            character, ctx.world, command.payload.get("data_id"), DataPayloadComponent
        )
        if data is None:
            return rejected("you are not carrying that data")
        data_id = str(data.id)
        _remove_item(ctx.world, data.id)
        replace_component(contract, replace(component, status="delivered"))
        return ok(
            DataDeliveredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(contract.id),),
                    character_id=str(character_id),
                    contract_id=str(contract.id),
                    data_id=data_id,
                )
            )
        )


class CollectPayoutHandler:
    command_type = "collect-payout"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contract, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), RunnerContractComponent
        )
        if contract is None:
            return rejected(error if error else "target is not a contract")
        component = contract.get_component(RunnerContractComponent)
        if component.accepted_by != str(character_id):
            return rejected("this is not your job")
        if component.status != "delivered":
            return rejected("nothing to collect yet")
        character = ctx.entity(character_id)
        if component.double_cross:
            replace_component(contract, replace(component, status="burned"))
            heat = _add_heat(character, ctx.epoch, DOUBLE_CROSS_HEAT)
            return ok(
                DoubleCrossRevealedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(contract.id),),
                        character_id=str(character_id),
                        contract_id=str(contract.id),
                    )
                ),
                HeatChangedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        character_id=str(character_id),
                        amount=heat,
                    )
                ),
            )
        replace_component(contract, replace(component, status="paid"))
        _add_scrip(character, ctx.world, component.payout)
        return ok(
            PayoutCollectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(contract.id),),
                    character_id=str(character_id),
                    contract_id=str(contract.id),
                    amount=component.payout,
                )
            )
        )


class BurnContactHandler:
    command_type = "burn-contact"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        fixer, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), FixerComponent
        )
        if fixer is None:
            return rejected(error if error else "target is not a contact")
        component = fixer.get_component(FixerComponent)
        if component.burned:
            return rejected("contact is already burned")
        replace_component(fixer, replace(component, burned=True))
        return ok(
            ContactBurnedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fixer.id),),
                    character_id=str(character_id),
                    contact_id=str(fixer.id),
                )
            )
        )


class PlantEvidenceHandler:
    command_type = "plant-evidence"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        target, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CharacterComponent
        )
        if target is None:
            return rejected(error if error else "target is not a person")
        room_id = container_of(ctx.entity(character_id))
        file_entity = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=f"evidence on {_name(target)}", kind="evidence"),
                BlackmailFileComponent(target_id=str(target.id)),
            ],
        )
        if room_id is not None and ctx.world.has_entity(room_id):
            ctx.world.get_entity(room_id).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), file_entity.id
            )
        return ok(
            EvidencePlantedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target.id), str(file_entity.id)),
                    character_id=str(character_id),
                    target_id=str(target.id),
                    file_id=str(file_entity.id),
                )
            )
        )


class BlackmailTargetHandler:
    command_type = "blackmail-target"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        target, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), CharacterComponent
        )
        if target is None:
            return rejected(error if error else "target is not a person")
        character = ctx.entity(character_id)
        file = _inventory_item(
            character, ctx.world, command.payload.get("file_id"), BlackmailFileComponent
        )
        if file is None:
            return rejected("you are not holding that file")
        component = file.get_component(BlackmailFileComponent)
        if component.used:
            return rejected("that leverage is already spent")
        if component.target_id != str(target.id):
            return rejected("that file is not about them")
        replace_component(file, replace(component, used=True))
        target.add_relationship(OwesFavor(reason="blackmail"), character_id)
        return ok(
            BlackmailAppliedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target.id),),
                    character_id=str(character_id),
                    target_id=str(target.id),
                )
            )
        )


class LeakFileHandler:
    command_type = "leak-file"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        file, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), BlackmailFileComponent
        )
        if file is None:
            return rejected(error if error else "target is not a file")
        component = file.get_component(BlackmailFileComponent)
        if component.leaked:
            return rejected("file is already leaked")
        replace_component(file, replace(component, leaked=True))
        subject_id = parse_entity_id(component.target_id)
        if (
            subject_id is not None
            and ctx.world.has_entity(subject_id)
            and ctx.world.get_entity(subject_id).has_component(CharacterComponent)
        ):
            _add_heat(ctx.world.get_entity(subject_id), ctx.epoch, LEAK_HEAT)
        return ok(
            FileLeakedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(file.id),),
                    character_id=str(character_id),
                    file_id=str(file.id),
                )
            )
        )


class ExtractAssetHandler:
    command_type = "extract-asset"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        asset, error = _reachable_component(
            ctx, character_id, command.payload.get("target_id"), AssetExtractionComponent
        )
        if asset is None:
            return rejected(error if error else "target is not an extractable asset")
        component = asset.get_component(AssetExtractionComponent)
        if component.extracted:
            return rejected("asset is already extracted")
        replace_component(asset, replace(component, extracted=True))
        return ok(
            AssetExtractedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(asset.id),),
                    character_id=str(character_id),
                    asset_id=str(asset.id),
                )
            )
        )


# --- Prompt fragments ----------------------------------------------------------------


def neonsim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    ctx = ComponentPromptContext.for_entity(world, character)
    if character.has_component(AccessLevelComponent):
        lines.extend(character.get_component(AccessLevelComponent).prompt_fragments(ctx))

    # reachable_ids() only returns ids of live entities, so no existence re-check needed.
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        entity_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, room=ctx.room, target=character
        )
        for component_type in (
            CyberpunkSiteComponent,
            CheckpointComponent,
            SafehouseComponent,
            DeviceComponent,
            RecordedEvidenceComponent,
            BlackMarketComponent,
            DataBrokerComponent,
            InformantComponent,
            ContrabandComponent,
            ClinicComponent,
            ImplantComponent,
            FixerComponent,
            HandlerComponent,
            RunnerContractComponent,
            BlackmailFileComponent,
            AssetExtractionComponent,
        ):
            if entity.has_component(component_type):
                if component_type is ImplantComponent and character.has_relationship(
                    HasImplant, entity_id
                ):
                    continue
                lines.extend(entity.get_component(component_type).prompt_fragments(entity_ctx))
    for _edge, implant in _installed_implants(character, world):
        implant_ctx = ComponentPromptContext.for_entity(
            world, implant, perspective=ctx.perspective, room=ctx.room, target=character
        )
        lines.extend(implant.get_component(ImplantComponent).prompt_fragments(implant_ctx))
    for component_type in (
        TraceTimerComponent,
        HeatComponent,
        WantedLevelComponent,
    ):
        if character.has_component(component_type):
            lines.extend(character.get_component(component_type).prompt_fragments(ctx))
    if character.has_component(DebtComponent):
        lines.append(f"Outstanding debt: {character.get_component(DebtComponent).amount} scrip.")
    return sorted(lines)


# --- Installation --------------------------------------------------------------------


def install_neonsim(actor) -> None:
    # Surveillance runs before trespass detection so a covert intruder is filmed on the
    # same tick they are caught and ejected.
    actor.register_consequence(SurveillanceConsequence())
    actor.register_consequence(TrespassDetectionConsequence())
    actor.register_consequence(TraceTimerConsequence())
    actor.register_consequence(HeatConsequence())
    actor.register_consequence(ImplantMaintenanceConsequence())


__all__ = [
    "AccessDeniedEvent",
    "AccessGrantedEvent",
    "AccessLevelComponent",
    "AccessTerminalHandler",
    "AlarmRaisedEvent",
    "BackdoorInstalledEvent",
    "BlackMarketComponent",
    "BlindSpotComponent",
    "BribeCheckpointHandler",
    "BuyContrabandHandler",
    "CallFavorHandler",
    "CameraComponent",
    "CameraDisabledEvent",
    "CameraLoopedEvent",
    "CaseLocationHandler",
    "CheckpointComponent",
    "CheckpointPassedEvent",
    "ClaimSafehouseHandler",
    "ClearWarrantHandler",
    "ContrabandBoughtEvent",
    "ContrabandComponent",
    "CredentialComponent",
    "CredentialUsedEvent",
    "CyberpunkSiteComponent",
    "DataBrokerComponent",
    "DataExfiltratedEvent",
    "DataPayloadComponent",
    "DataSoldEvent",
    "DebtPaidEvent",
    "DeployDroneHandler",
    "DeviceComponent",
    "DeviceInspectedEvent",
    "DisableCameraHandler",
    "DistrictEnteredEvent",
    "DoorUnlockedEvent",
    "DroneDeployedEvent",
    "EnterDistrictHandler",
    "EscalatePrivilegesHandler",
    "EvadeTraceHandler",
    "EvidenceRecordedEvent",
    "EvidenceWipedEvent",
    "ExfiltrateDataHandler",
    "ExploitComponent",
    "FavorCalledEvent",
    "HackFailedEvent",
    "HackSucceededEvent",
    "HackableComponent",
    "HeatChangedEvent",
    "HeatComponent",
    "HeatConsequence",
    "HideFromLawHandler",
    "IdentitySpoofedEvent",
    "InformantComponent",
    "InformantTurnedEvent",
    "InsideZone",
    "InspectDeviceHandler",
    "InstallBackdoorHandler",
    "JamSensorHandler",
    "LawResponseEvent",
    "LocationCasedEvent",
    "LoopCameraHandler",
    "NetworkScannedEvent",
    "NetworkTracedEvent",
    "OwesFavor",
    "PayDebtHandler",
    "PostBountyHandler",
    "PrivilegesEscalatedEvent",
    "PublicAccessComponent",
    "RecordedEvidenceComponent",
    "RestrictedAreaComponent",
    "RunExploitHandler",
    "SabotageSystemHandler",
    "SafehouseClaimedEvent",
    "SafehouseComponent",
    "ScanNetworkHandler",
    "SecurityZoneComponent",
    "SellDataHandler",
    "SensorJammedEvent",
    "ShowCredentialsHandler",
    "SneakCheckpointHandler",
    "SpoofIdentityHandler",
    "SurveillanceConsequence",
    "SurveillanceCoverageComponent",
    "SystemSabotagedEvent",
    "TerminalAccessedEvent",
    "TraceEvadedEvent",
    "TraceNetworkHandler",
    "TraceStartedEvent",
    "TraceTimerComponent",
    "TraceTimerConsequence",
    "TrespassDetectedEvent",
    "TrespassDetectionConsequence",
    "TurnInformantHandler",
    "UnlockDoorHandler",
    "UseCredentialHandler",
    "WantedLevelChangedEvent",
    "WantedLevelComponent",
    "WarrantClearedEvent",
    "WipeEvidenceHandler",
    "AugmentationSlotsComponent",
    "ClinicComponent",
    "DisableImplantHandler",
    "ExploitImplantHandler",
    "HasImplant",
    "ImplantComponent",
    "ImplantDisabledEvent",
    "ImplantExploitedEvent",
    "ImplantInstalledEvent",
    "ImplantLicensedEvent",
    "ImplantMaintenanceConsequence",
    "ImplantOverclockedEvent",
    "ImplantRemovedEvent",
    "ImplantScannedEvent",
    "ImplantServicedEvent",
    "InstallImplantHandler",
    "LicenseImplantHandler",
    "OverclockImplantHandler",
    "RemoveImplantHandler",
    "ScanImplantHandler",
    "ServiceImplantHandler",
    "SideEffectTriggeredEvent",
    "AssetExtractedEvent",
    "AssetExtractionComponent",
    "BlackmailAppliedEvent",
    "BlackmailFileComponent",
    "BlackmailTargetHandler",
    "BurnContactHandler",
    "CollectPayoutHandler",
    "ContactBurnedEvent",
    "CorporationComponent",
    "DataDeliveredEvent",
    "DeliverDataHandler",
    "DoubleCrossRevealedEvent",
    "EvidencePlantedEvent",
    "ExtractAssetHandler",
    "FileLeakedEvent",
    "FixerComponent",
    "FixerJobAcceptedEvent",
    "HandlerComponent",
    "HandlerMetEvent",
    "LeakFileHandler",
    "MeetHandlerHandler",
    "PayoutCollectedEvent",
    "PlantEvidenceHandler",
    "RunnerContractComponent",
    "TakeFixerJobHandler",
    "install_neonsim",
    "neonsim_fragments",
]
