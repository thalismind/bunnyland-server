"""Declarative neonsim generation contributions."""

from ...core.generation import GenerationDelta, GenerationRequest
from ...worldgen.enrichment import GenerationContext, generation_mentions, generation_wants
from .mechanics import (
    AccessLevelComponent,
    AugmentationSlotsComponent,
    BlackMarketComponent,
    CameraComponent,
    CheckpointComponent,
    ClinicComponent,
    CyberpunkSiteComponent,
    DataBrokerComponent,
    DeviceComponent,
    FixerComponent,
    HackableComponent,
    RestrictedAreaComponent,
    RunnerContractComponent,
    SafehouseComponent,
    SecurityZoneComponent,
    SurveillanceCoverageComponent,
)

CAPABILITIES = (
    "bunnyland.neonsim.black-market",
    "bunnyland.neonsim.camera",
    "bunnyland.neonsim.checkpoint",
    "bunnyland.neonsim.clinic",
    "bunnyland.neonsim.cyberpunk-site",
    "bunnyland.neonsim.data-broker",
    "bunnyland.neonsim.fixer",
    "bunnyland.neonsim.netrunner",
    "bunnyland.neonsim.safehouse",
    "bunnyland.neonsim.security-zone",
)

ALIASES = {
    "black-market": "bunnyland.neonsim.black-market",
    "camera": "bunnyland.neonsim.camera",
    "checkpoint": "bunnyland.neonsim.checkpoint",
    "clinic": "bunnyland.neonsim.clinic",
    "cyberpunk-site": "bunnyland.neonsim.cyberpunk-site",
    "data-broker": "bunnyland.neonsim.data-broker",
    "fixer": "bunnyland.neonsim.fixer",
    "netrunner": "bunnyland.neonsim.netrunner",
    "safehouse": "bunnyland.neonsim.safehouse",
    "security-zone": "bunnyland.neonsim.security-zone",
}


class NeonGenerationEnricher:
    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        ctx = GenerationContext.from_request(request)
        components = {}

        def add(component):
            components[type(component)] = component

        if ctx.is_character:
            if generation_wants(ctx, "fixer") or generation_mentions(ctx, "fixer"):
                add(FixerComponent(name=ctx.name))
            if generation_wants(ctx, "netrunner") or generation_mentions(
                ctx, "netrunner", "runner", "hacker"
            ):
                add(AccessLevelComponent(clearance=2))
                add(AugmentationSlotsComponent())
        else:
            if generation_wants(ctx, "cyberpunk-site") or generation_mentions(
                ctx, "district", "arcology", "corp", "nightclub", "plaza", "market", "alley"
            ):
                add(CyberpunkSiteComponent(site_type=ctx.name))
            if generation_wants(ctx, "security-zone") or generation_mentions(
                ctx, "restricted", "secure", "vault"
            ):
                add(SecurityZoneComponent(clearance_required=2))
                add(RestrictedAreaComponent())
            if generation_wants(ctx, "checkpoint") or generation_mentions(
                ctx, "checkpoint", "turnstile"
            ):
                add(CheckpointComponent(clearance_required=2, bribe_cost=20))
            if generation_wants(ctx, "safehouse") or generation_mentions(
                ctx, "safehouse", "hideout", "flop"
            ):
                add(SafehouseComponent())
            if generation_wants(ctx, "camera") or generation_mentions(ctx, "camera", "cctv"):
                add(DeviceComponent(device_type="camera"))
                add(CameraComponent())
                add(SurveillanceCoverageComponent())
            if generation_wants(ctx, "terminal") or generation_mentions(
                ctx, "terminal", "server", "console"
            ):
                add(DeviceComponent(device_type="terminal"))
                add(HackableComponent(security=2))
            if generation_wants(ctx, "black-market") or generation_mentions(
                ctx, "vendor", "black market", "dealer"
            ):
                add(BlackMarketComponent())
            if generation_wants(ctx, "data-broker") or generation_mentions(ctx, "fence", "broker"):
                add(DataBrokerComponent())
            if generation_wants(ctx, "clinic") or generation_mentions(
                ctx, "clinic", "ripperdoc", "surgeon"
            ):
                licensed = not generation_mentions(ctx, "ripperdoc", "street", "back-alley")
                add(ClinicComponent(licensed=licensed))
            if generation_wants(ctx, "contract") or generation_mentions(
                ctx, "contract", "job posting", "gig"
            ):
                add(RunnerContractComponent())
        return GenerationDelta(
            components=tuple(components.values()),
            satisfies=tuple(
                capability for capability in request.capabilities if capability in CAPABILITIES
            ),
        )


GENERATION_ENRICHER = NeonGenerationEnricher()

__all__ = ["GENERATION_ENRICHER", "NeonGenerationEnricher"]
