"""Opt-in save/reload checkpoints."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from relics import Component

from ...core.actions import ActionArgument, ActionDefinition, ActionExample, ActionPattern
from ...core.commands import CommandCost, SubmittedCommand
from ...core.components import IdentityComponent, RoomComponent
from ...core.ecs import container_of, parse_entity_id, reachable_ids
from ...core.events import DomainEvent, EventVisibility, event_base
from ...core.handlers import HandlerContext, HandlerResult, planned, rejected
from ...core.mutations import MutationPlan
from ...prompts import ComponentPromptContext

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SaveCheckpointComponent(Component):
    """Marker for intentionally placed save/reload checkpoint objects."""

    label: str = "checkpoint"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        name = _entity_name(ctx.entity)
        return (f"Checkpoint {name}: save and reload available.",)


class CheckpointSavedEvent(DomainEvent):
    character_id: str
    checkpoint_id: str
    path: str
    saved_at_epoch: int


class CheckpointReloadRequestedEvent(DomainEvent):
    character_id: str
    checkpoint_id: str
    path: str


class CheckpointReloadedEvent(DomainEvent):
    character_id: str
    checkpoint_id: str
    path: str
    saved_at_epoch: int


@dataclass(frozen=True)
class _PendingReload:
    character_id: str
    checkpoint_id: str
    path: str


def _entity_name(entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    if entity.has_component(RoomComponent):
        return entity.get_component(RoomComponent).title
    return str(entity.id)


def _room_id(ctx: HandlerContext, character_id) -> str | None:
    room_id = container_of(ctx.world.get_entity(character_id))
    return str(room_id) if room_id is not None else None


def _persistence(ctx: HandlerContext):
    actor = getattr(ctx, "actor", None)
    return getattr(actor, "persistence", None)


def _configured_save_path(ctx: HandlerContext) -> Path | None:
    persistence = _persistence(ctx)
    raw = getattr(persistence, "save_path", None)
    return Path(raw) if raw else None


def _configured_meta(ctx: HandlerContext):
    from ...persistence import WorldMeta

    persistence = _persistence(ctx)
    meta = getattr(persistence, "meta", None)
    if meta is not None:
        return meta
    meta = WorldMeta()
    persistence.meta = meta
    return meta


def _reachable_checkpoint(
    ctx: HandlerContext, command: SubmittedCommand
) -> tuple[object | None, object | None, HandlerResult | None]:
    character_id = parse_entity_id(command.character_id)
    target_id = parse_entity_id(command.payload.get("target_id"))
    if character_id is None:
        return None, None, rejected("invalid character id")
    if target_id is None:
        return None, None, rejected("invalid checkpoint id")
    if not ctx.world.has_entity(character_id):
        return None, None, rejected("character does not exist")
    if not ctx.world.has_entity(target_id):
        return None, None, rejected("checkpoint does not exist")
    character = ctx.world.get_entity(character_id)
    if target_id not in reachable_ids(ctx.world, character):
        return None, None, rejected("checkpoint is not reachable")
    checkpoint = ctx.world.get_entity(target_id)
    if not checkpoint.has_component(SaveCheckpointComponent):
        return None, None, rejected("target is not a checkpoint")
    return character_id, checkpoint, None


class SaveCheckpointHandler:
    command_type = "save-checkpoint"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id, checkpoint, error = _reachable_checkpoint(ctx, command)
        if error is not None:
            return error
        save_path = _configured_save_path(ctx)
        if save_path is None:
            return rejected("server was not started with --save")

        from ...persistence import save_world

        stamped = save_world(ctx.actor, save_path, meta=_configured_meta(ctx))
        return planned(
            MutationPlan(),
            CheckpointSavedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx, character_id),
                    target_ids=(str(checkpoint.id),),
                    character_id=str(character_id),
                    checkpoint_id=str(checkpoint.id),
                    path=str(save_path),
                    saved_at_epoch=stamped.saved_at_epoch,
                )
            ),
            ctx=ctx,
        )


class CheckpointReloadService:
    def __init__(self) -> None:
        self.pending: _PendingReload | None = None

    def request(self, pending: _PendingReload) -> None:
        if self.pending is None:
            self.pending = pending

    async def after_tick(self, actor) -> None:
        pending = self.pending
        if pending is None:
            return
        self.pending = None
        persistence = actor.persistence
        try:
            from ...persistence import WorldMeta, reload_world

            meta = persistence.meta if persistence.meta is not None else WorldMeta()
            reloaded_meta = reload_world(
                actor,
                pending.path,
                meta=meta,
                registry=actor.plugins,
                plugin_context=persistence.plugin_context,
            )
        except Exception:
            LOG.exception("checkpoint reload failed from %s", pending.path)
            return
        await actor.bus.publish(
            CheckpointReloadedEvent(
                **event_base(
                    actor.epoch,
                    visibility=EventVisibility.SYSTEM,
                    actor_id=pending.character_id,
                    target_ids=(pending.checkpoint_id,),
                    character_id=pending.character_id,
                    checkpoint_id=pending.checkpoint_id,
                    path=pending.path,
                    saved_at_epoch=reloaded_meta.saved_at_epoch,
                )
            )
        )


class ReloadCheckpointHandler:
    command_type = "reload-checkpoint"

    def __init__(self, service: CheckpointReloadService) -> None:
        self.service = service

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id, checkpoint, error = _reachable_checkpoint(ctx, command)
        if error is not None:
            return error
        save_path = _configured_save_path(ctx)
        if save_path is None:
            return rejected("server was not started with --save")
        if not save_path.exists():
            return rejected("save file does not exist")

        self.service.request(
            _PendingReload(
                character_id=str(character_id),
                checkpoint_id=str(checkpoint.id),
                path=str(save_path),
            )
        )
        return planned(
            MutationPlan(),
            CheckpointReloadRequestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx, character_id),
                    target_ids=(str(checkpoint.id),),
                    character_id=str(character_id),
                    checkpoint_id=str(checkpoint.id),
                    path=str(save_path),
                )
            ),
            ctx=ctx,
        )


def checkpoint_action_definitions() -> tuple[ActionDefinition, ...]:
    target_arg = ActionArgument(
        title="Checkpoint",
        description="Reachable checkpoint entity.",
        kind="entity",
        required=True,
    )
    return (
        ActionDefinition(
            command_type="save-checkpoint",
            tool_name="save_checkpoint",
            title="Save Checkpoint",
            description="Save the world at a reachable checkpoint.",
            icon="💾",
            cost=CommandCost(action=1),
            arguments={"target_id": target_arg},
            natural_patterns=(
                ActionPattern("save at {target_id}"),
                ActionPattern("save checkpoint {target_id}"),
            ),
            examples=(ActionExample("save at typewriter", natural=True),),
        ),
        ActionDefinition(
            command_type="reload-checkpoint",
            tool_name="reload_checkpoint",
            title="Reload Checkpoint",
            description="Reload the world from the configured save at a reachable checkpoint.",
            icon="↩️",
            cost=CommandCost(action=1),
            arguments={"target_id": target_arg},
            natural_patterns=(
                ActionPattern("reload from {target_id}"),
                ActionPattern("reload checkpoint {target_id}"),
            ),
            examples=(ActionExample("reload from bonfire", natural=True),),
        ),
    )


def install_checkpoints(actor) -> None:
    service = CheckpointReloadService()
    actor.register_handler(SaveCheckpointHandler())
    actor.register_handler(ReloadCheckpointHandler(service))
    actor.register_after_tick(service.after_tick)


__all__ = [
    "CheckpointReloadRequestedEvent",
    "CheckpointReloadService",
    "CheckpointReloadedEvent",
    "CheckpointSavedEvent",
    "ReloadCheckpointHandler",
    "SaveCheckpointComponent",
    "SaveCheckpointHandler",
    "checkpoint_action_definitions",
    "install_checkpoints",
]
