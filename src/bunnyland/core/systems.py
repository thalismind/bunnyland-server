"""Core passive-simulation systems (spec sections 5.6, 6.2, 23.1).

These are Relics ``System`` subclasses run synchronously inside ``world.tick(delta)``,
where ``delta`` is elapsed *game* seconds. They mutate ECS state only; domain events are
emitted by the world actor, which orchestrates the tick. Components are replaced, never
mutated in place.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING

from relics import Frequency, System

from .claim_timeout import (
    CLAIM_FALLBACK_LLM,
    CLAIM_TIMEOUT_DEFAULT_SECONDS,
    normalize_claim_timeout,
)
from .components import (
    ActionPointsComponent,
    CharacterComponent,
    FocusPointsComponent,
    SuspendedComponent,
    WorldClockComponent,
)
from .controllers import (
    BehaviorControllerComponent,
    ClaimTimeoutComponent,
    DiscordControllerComponent,
    LLMControllerComponent,
    MCPControllerComponent,
    ScriptedControllerComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
)
from .ecs import parse_entity_id, replace_component, spawn_entity
from .edges import ControlledBy
from .events import ControllerChangedEvent

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .world_actor import WorldActor

SECONDS_PER_HOUR = 3600.0


class WorldClockSystem(System):
    """Advance the world clock by the tick's game-seconds delta (spec 5.6 phase 2)."""

    def query(self):
        return self.q.with_all([WorldClockComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        for entity in entities:
            clock = entity.get_component(WorldClockComponent)
            advanced = int(delta * clock.time_scale)
            replace_component(
                entity,
                replace(
                    clock,
                    game_time_seconds=clock.game_time_seconds + advanced,
                    tick_index=clock.tick_index + 1,
                ),
            )


def _regen(current: float, maximum: float, overflow_maximum: float | None,
           regen_per_hour: float, delta_seconds: float) -> float:
    cap = overflow_maximum if overflow_maximum is not None else maximum
    gained = regen_per_hour * (delta_seconds / SECONDS_PER_HOUR)
    return min(cap, current + gained)


class ActionFocusRegenSystem(System):
    """Regenerate Action and Focus for *all* characters in real time (spec 6.2).

    Includes suspended characters: they regenerate but never spend, so they recharge
    fully. Spending is handled by command execution, not here.
    """

    def query(self):
        return self.q.with_any([ActionPointsComponent, FocusPointsComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        for entity in entities:
            if entity.has_component(ActionPointsComponent):
                ap = entity.get_component(ActionPointsComponent)
                new_current = _regen(
                    ap.current, ap.maximum, ap.overflow_maximum, ap.regen_per_hour, delta
                )
                if new_current != ap.current:
                    replace_component(entity, replace(ap, current=new_current))
            if entity.has_component(FocusPointsComponent):
                fp = entity.get_component(FocusPointsComponent)
                new_current = _regen(
                    fp.current, fp.maximum, fp.overflow_maximum, fp.regen_per_hour, delta
                )
                if new_current != fp.current:
                    replace_component(entity, replace(fp, current=new_current))


class ClaimTimeoutSystem:
    """After-tick system that expires inactive player controller claims.

    The server owns timeout policy: default timeout and affected controller kinds. The
    controller component owns player preference: per-claim timeout and fallback kind.
    Time is wall-clock seconds so simulation time scaling cannot expire claims early.
    """

    def __init__(
        self,
        *,
        default_timeout_seconds: int = CLAIM_TIMEOUT_DEFAULT_SECONDS,
        controller_kinds: Iterable[str] = ("discord", "web"),
        default_llm_model: str = "deepseek-v4-flash",
        default_llm_provider: str = "ollama",
        now: Callable[[], float] = time.time,
    ) -> None:
        normalized_default = normalize_claim_timeout(default_timeout_seconds)
        self.default_timeout_seconds = (
            normalized_default
            if normalized_default is not None
            else CLAIM_TIMEOUT_DEFAULT_SECONDS
        )
        self.controller_kinds = frozenset(
            kind.strip().lower().replace("_", "-") for kind in controller_kinds if kind
        )
        self.default_llm_model = default_llm_model
        self.default_llm_provider = default_llm_provider
        self.now = now

    async def __call__(self, actor: WorldActor) -> None:
        from ..claims import controller_claim, transfer_claim

        if not self.controller_kinds:
            return
        now_unix = int(self.now())
        expired = []
        characters = list(
            actor.world.query().with_all([CharacterComponent]).execute_entities()
        )
        for character in characters:
            for _edge, controller_id in character.get_relationships(ControlledBy):
                if not actor.world.has_entity(controller_id):
                    continue
                controller = actor.world.get_entity(controller_id)
                kind = self._controller_kind(controller)
                if kind not in self.controller_kinds:
                    continue
                if not controller.has_component(ClaimTimeoutComponent):
                    continue
                claim = controller.get_component(ClaimTimeoutComponent)
                last_active = claim.last_command_unix or claim.claimed_at_unix
                timeout = claim.timeout_seconds or self.default_timeout_seconds
                if now_unix - last_active >= timeout:
                    expired.append((character, controller, claim))

        for character, old_controller, claim in expired:
            active_claim = controller_claim(old_controller)
            existing = self._existing_fallback(
                actor,
                claim.fallback_controller,
                claim_id=active_claim.claim_id if active_claim is not None else "",
            )
            if existing is not None:
                controller = existing
                kind = self._controller_kind(controller)
            elif claim.fallback_controller == CLAIM_FALLBACK_LLM:
                controller = spawn_entity(
                    actor.world,
                    [
                        LLMControllerComponent(
                            profile_name=claim.llm_profile_name or "default",
                            model=claim.llm_model or self.default_llm_model,
                            provider=claim.llm_provider or self.default_llm_provider,
                        )
                    ]
                )
                kind = "llm"
            else:
                controller = spawn_entity(
                    actor.world,
                    [SuspendedControllerComponent(reason=claim.fallback_reason)]
                )
                kind = "suspended"
            transfer_claim(old_controller, controller)
            if kind == "suspended":
                generation = actor.suspend(
                    character.id, controller.id, reason=claim.fallback_reason
                )
            else:
                generation = actor.assign_controller(character.id, controller.id)
                if character.has_component(SuspendedComponent):
                    character.remove_component(SuspendedComponent)
            await actor.bus.publish(
                ControllerChangedEvent(
                    **actor._event_base(
                        actor_id=str(character.id),
                        generation=generation,
                        controller_kind=kind,
                    )
                )
            )

    @staticmethod
    def _controller_kind(controller) -> str:
        if controller.has_component(DiscordControllerComponent):
            return "discord"
        if controller.has_component(WebControllerComponent):
            return "web"
        if controller.has_component(MCPControllerComponent):
            return "mcp"
        if controller.has_component(LLMControllerComponent):
            return "llm"
        if controller.has_component(BehaviorControllerComponent):
            return "behavioral"
        if controller.has_component(ScriptedControllerComponent):
            return "scripted"
        if controller.has_component(SuspendedControllerComponent):
            return "suspended"
        return "unknown"

    def _existing_fallback(
        self,
        actor: WorldActor,
        fallback_controller: str,
        *,
        claim_id: str,
    ):
        from ..claims import controller_claim

        controller_id = parse_entity_id(fallback_controller)
        if controller_id is None or not actor.world.has_entity(controller_id):
            return None
        controller = actor.world.get_entity(controller_id)
        if self._controller_kind(controller) == "unknown":
            return None
        existing_claim = controller_claim(controller)
        if existing_claim is not None and existing_claim.claim_id != claim_id:
            return None
        return controller


__all__ = ["ActionFocusRegenSystem", "ClaimTimeoutSystem", "WorldClockSystem"]
