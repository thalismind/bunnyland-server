"""Optional, lazily imported 3D chaos aura."""

from .mechanics import ChaosInfluenceComponent


def install_voidsim_3d(actor, context) -> None:
    if context.plugins is None or not context.plugins.enabled("bunnyland.3d"):
        return
    from bunnyland_3d import (
        ParticleSystem3D,
        VisualEffectDefinition,
        VisualEffectLightningLayer,
        VisualEffectParticleLayer,
        VisualEffectStateRule,
        register_particle_systems,
        register_visual_effect_state_rules,
        register_visual_effects,
    )

    owner = "bunnyland.voidsim"
    system_key = f"{owner}/chaos-motes"
    effect_key = f"{owner}/chaos"
    register_particle_systems(
        actor,
        owner,
        (
            ParticleSystem3D(
                system_key,
                blending="additive",
                vertical_motion="drift",
                vertical_scale=0.2,
                lateral_wobble=0.3,
                pulse_amount=0.35,
                pulse_speed=7.0,
            ),
        ),
    )
    register_visual_effects(
        actor,
        owner,
        (
            VisualEffectDefinition(
                effect_key,
                particle_layers=(
                    VisualEffectParticleLayer(
                        system_key,
                        count=34,
                        bounds=(0.9, 1.6, 0.9),
                        color="#c13cff",
                        size=0.075,
                        speed=0.32,
                        opacity=0.86,
                    ),
                ),
                lightning_layers=(
                    VisualEffectLightningLayer(
                        color="#a020f0",
                        bolt_count=4,
                        segment_count=9,
                        radius=0.62,
                        height=1.45,
                        jitter=0.16,
                        opacity=0.82,
                        flicker_speed=9.0,
                    ),
                ),
            ),
        ),
    )
    register_visual_effect_state_rules(
        actor,
        owner,
        (
            VisualEffectStateRule(
                f"{owner}/chaos-state",
                ChaosInfluenceComponent,
                lambda entity: entity.has_component(ChaosInfluenceComponent),
                effect_key,
            ),
        ),
    )


__all__ = ["install_voidsim_3d"]
