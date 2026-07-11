"""Declarative Toon Sim generation contributions."""

from dataclasses import dataclass

from bunnyland.simpacks.toonsim.mechanics import (
    PlacedOn,
    PortableComponent,
    SpriteBoundsComponent,
    ToonWorldgenHook,
    _position_on_surface,
    _surface_entities,
)

from ...core.ecs import parse_entity_id
from ...core.events import ObjectGeneratedEvent
from ...core.generation import GenerationDelta, GenerationEdge
from ...worldgen.enrichment import ComponentPlanEnricher

CAPABILITIES = ()
ALIASES = {}


@dataclass(frozen=True)
class ToonGenerationEnricher:
    components: ComponentPlanEnricher = ComponentPlanEnricher(
        ToonWorldgenHook, provided_capabilities=CAPABILITIES
    )

    @property
    def capabilities(self):
        return self.components.capabilities

    def bind_components(self, component_types):
        return ToonGenerationEnricher(self.components.bind_components(component_types))

    def enrich(self, request):
        return self.components.enrich(request)

    def finalize(self, actor, event):
        if not isinstance(event, ObjectGeneratedEvent):
            return GenerationDelta()
        entity_id = parse_entity_id(event.entity_id)
        room_id = parse_entity_id(event.room_id)
        if entity_id is None or room_id is None:
            return GenerationDelta()
        entity = actor.world.get_entity(entity_id)
        if not entity.has_component(PortableComponent) or not entity.has_component(
            SpriteBoundsComponent
        ):
            return GenerationDelta()
        room = actor.world.get_entity(room_id)
        surfaces = _surface_entities(actor.world, room, entity.id)
        if not surfaces:
            return GenerationDelta()
        surface = surfaces[0]
        return GenerationDelta(
            components=(_position_on_surface(entity, surface),),
            edges=(GenerationEdge(PlacedOn(), surface.id),),
        )


GENERATION_ENRICHER = ToonGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "ToonGenerationEnricher", "ToonWorldgenHook"]
