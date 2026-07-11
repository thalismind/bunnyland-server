"""Declarative Toon Sim generation contributions."""

from bunnyland.core.components import (
    CharacterComponent,
    ContainerComponent,
    DoorComponent,
    IdentityComponent,
    PortableComponent,
    RoomComponent,
)

from ...core.generation import (
    GenerationDelta,
    GenerationEdge,
    GenerationRequest,
    GenerationTarget,
)
from .mechanics import (
    FURNITURE_KINDS,
    LAYER_BACKGROUND,
    LAYER_CHARACTER,
    LAYER_FURNITURE,
    LAYER_ITEM,
    ROOM_HEIGHT,
    ROOM_WIDTH,
    SURFACE_KINDS,
    PlacedOn,
    SpriteBoundsComponent,
    SpriteImageComponent,
    SpriteLayerComponent,
    SpritePositionComponent,
    SpriteScaleComponent,
    ToonRoomComponent,
    _clamp_position,
    _stable_range,
    _stable_unit,
)

CAPABILITIES = ()


def _component(components, component_type):
    return next((value for value in components if isinstance(value, component_type)), None)


def _defaults(base_components, entity_kind: str):
    room = _component(base_components, RoomComponent)
    character = _component(base_components, CharacterComponent)
    identity = _component(base_components, IdentityComponent)
    kind = identity.kind if identity is not None else entity_kind
    if room is not None:
        return LAYER_BACKGROUND, SpriteBoundsComponent(width=ROOM_WIDTH, height=ROOM_HEIGHT), kind
    if character is not None:
        return LAYER_CHARACTER, SpriteBoundsComponent(width=5.0, height=8.0, solid=True), kind
    if kind in SURFACE_KINDS:
        return LAYER_FURNITURE, SpriteBoundsComponent(width=22.0, height=12.0, solid=True), kind
    if kind in FURNITURE_KINDS or _component(base_components, ContainerComponent) is not None:
        return LAYER_FURNITURE, SpriteBoundsComponent(width=14.0, height=10.0, solid=True), kind
    if _component(base_components, DoorComponent) is not None:
        return LAYER_ITEM, SpriteBoundsComponent(width=10.0, height=8.0), kind
    if _component(base_components, PortableComponent) is not None:
        return LAYER_ITEM, SpriteBoundsComponent(), kind
    return None, None, kind


def _position(request, base_components, bounds, kind):
    if _component(base_components, RoomComponent) is not None:
        return SpritePositionComponent(), None
    if _component(base_components, CharacterComponent) is not None:
        return (
            _clamp_position(
                _stable_range(30.0, 70.0, request.source_key, "character-x"),
                _stable_range(55.0, 86.0, request.source_key, "character-y"),
                bounds,
            ),
            None,
        )
    if _component(base_components, DoorComponent) is not None or kind == "door":
        name = request.description.casefold()
        directions = {
            "north": (50.0, 4.0),
            "south": (50.0, 96.0),
            "east": (96.0, 50.0),
            "west": (4.0, 50.0),
        }
        for direction, (x, y) in directions.items():
            if direction in name:
                return _clamp_position(x, y, bounds), None
        return (
            _clamp_position(
                _stable_range(10.0, 90.0, request.source_key, "door-x"),
                _stable_range(8.0, 16.0, request.source_key, "door-y"),
                bounds,
            ),
            None,
        )
    if kind in FURNITURE_KINDS or _component(base_components, ContainerComponent) is not None:
        return (
            _clamp_position(
                _stable_range(14.0, 86.0, request.source_key, "furniture-x"),
                _stable_range(18.0, 72.0, request.source_key, "furniture-y"),
                bounds,
            ),
            None,
        )
    surfaces = tuple(
        key
        for key, candidate_kind in request.context.get("room_objects", ())
        if candidate_kind in SURFACE_KINDS
    )
    if _component(base_components, PortableComponent) is not None and surfaces:
        surface_key = surfaces[
            int(_stable_unit(request.source_key, "surface") * len(surfaces)) % len(surfaces)
        ]
        surface_bounds = SpriteBoundsComponent(width=22.0, height=12.0, solid=True)
        surface_position = _clamp_position(
            _stable_range(14.0, 86.0, surface_key, "furniture-x"),
            _stable_range(18.0, 72.0, surface_key, "furniture-y"),
            surface_bounds,
        )
        usable_w = max(0.0, surface_bounds.width - bounds.width)
        usable_h = max(0.0, surface_bounds.height - bounds.height)
        return (
            _clamp_position(
                surface_position.x
                - usable_w / 2.0
                + _stable_range(0.0, usable_w, request.source_key, "surface-x"),
                surface_position.y
                - usable_h / 2.0
                + _stable_range(0.0, usable_h, request.source_key, "surface-y"),
                bounds,
            ),
            surface_key,
        )
    return (
        _clamp_position(
            _stable_range(18.0, 82.0, request.source_key, "item-x"),
            _stable_range(58.0, 90.0, request.source_key, "item-y"),
            bounds,
        ),
        None,
    )


class ToonGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        base_components = tuple(request.context.get("base_components", ()))
        existing = {type(component) for component in base_components}
        layer, default_bounds, kind = _defaults(base_components, request.entity_kind)
        components = []
        if layer is not None and SpriteLayerComponent not in existing:
            components.append(SpriteLayerComponent(layer=layer))
        if SpriteImageComponent not in existing:
            components.append(SpriteImageComponent())
        if SpriteScaleComponent not in existing:
            components.append(SpriteScaleComponent())
        bounds = _component(base_components, SpriteBoundsComponent) or default_bounds
        if bounds is not None and SpriteBoundsComponent not in existing:
            components.append(bounds)
        if _component(base_components, RoomComponent) is not None:
            if ToonRoomComponent not in existing:
                components.append(ToonRoomComponent())
        edges = ()
        if bounds is not None and SpritePositionComponent not in existing:
            position, surface_key = _position(request, base_components, bounds, kind)
            components.append(position)
            if surface_key is not None:
                edges = (GenerationEdge(PlacedOn(), GenerationTarget(surface_key)),)
        return GenerationDelta(components=tuple(components), edges=edges)


GENERATION_ENRICHER = ToonGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "ToonGenerationEnricher"]
