"""Example server plugin: greet Discord players after they claim a character.

Run with:

    bunnyland serve --plugin examples.motd_claim --discord

The claim event is generic. This plugin treats the world as the source of truth: it uses
the event's controller entity id to look up the controller component and only creates a
MOTD for Discord controllers.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Frequency, System

from bunnyland.core import (
    ControllerOutboxMessageComponent,
    DiscordControllerComponent,
    IdentityComponent,
    parse_entity_id,
)
from bunnyland.core.ecs import replace_component, spawn_entity
from bunnyland.core.events import CharacterClaimedEvent
from bunnyland.plugins import EcsContribution, Plugin, RuntimeContribution

MOTD_TEXT = "Welcome to Bunnyland. Today's tip: use !look before your first move."
MOTD_TTL_SECONDS = 3600


@dataclass(frozen=True)
class MotdMessageComponent(Component):
    text: str
    created_at_epoch: int
    expires_at_epoch: int
    queued_for_delivery: bool = False


@dataclass(frozen=True)
class HasMotdMessage(Edge):
    """character -> MOTD message entity.

    A character can receive multiple MOTDs over time, so the repeatable relationship is an
    edge plus separate message entities, not a list on the character component.
    """

    controller_id: str
    generation: int


class MotdOutboxSystem(System):
    """Mark fresh MOTD rows as ready for an external Discord sender to deliver."""

    def query(self):
        return self.q.with_all([MotdMessageComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        del components, delta
        for entity in entities:
            message = entity.get_component(MotdMessageComponent)
            if not message.queued_for_delivery:
                replace_component(entity, replace(message, queued_for_delivery=True))


class MotdClaimListener:
    def __init__(self, actor, *, text: str = MOTD_TEXT, ttl_seconds: int = MOTD_TTL_SECONDS):
        self.actor = actor
        self.text = text
        self.ttl_seconds = ttl_seconds

    def __call__(self, event: CharacterClaimedEvent) -> None:
        character_id = parse_entity_id(event.character_id)
        controller_id = parse_entity_id(event.controller_id)
        if character_id is None or controller_id is None:
            return
        if not self.actor.world.has_entity(character_id) or not self.actor.world.has_entity(
            controller_id
        ):
            return

        controller = self.actor.world.get_entity(controller_id)
        if not controller.has_component(DiscordControllerComponent):
            return

        character = self.actor.world.get_entity(character_id)
        message = spawn_entity(
            self.actor.world,
            [
                IdentityComponent(name="Message of the day", kind="motd_message"),
                ControllerOutboxMessageComponent(
                    controller_id=event.controller_id,
                    text=self.text,
                    created_at_epoch=event.world_epoch,
                ),
                MotdMessageComponent(
                    text=self.text,
                    created_at_epoch=event.world_epoch,
                    expires_at_epoch=event.world_epoch + self.ttl_seconds,
                ),
            ],
        )
        character.add_relationship(
            HasMotdMessage(
                controller_id=event.controller_id,
                generation=event.generation,
            ),
            message.id,
        )


def install_motd_claim_listener(actor) -> None:
    actor.bus.subscribe(CharacterClaimedEvent, MotdClaimListener(actor))


def bunnyland_plugins() -> list[Plugin]:
    return [
        Plugin(
            id="motd_claim",
            name="MOTD Claim Greeting Example",
            version="0.1.0",
            default_enabled=True,
            ecs=EcsContribution(
                components=(MotdMessageComponent,),
                edges=(HasMotdMessage,),
                systems=(MotdOutboxSystem,),
            ),
            runtime=RuntimeContribution(integration_factories=(install_motd_claim_listener,)),
        )
    ]


__all__ = [
    "HasMotdMessage",
    "MotdMessageComponent",
    "MotdOutboxSystem",
    "bunnyland_plugins",
    "install_motd_claim_listener",
]
