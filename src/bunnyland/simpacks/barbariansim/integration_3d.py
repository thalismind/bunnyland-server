"""Optional, lazily imported 3D poison aura."""

from .mechanics import PoisonComponent


def install_barbariansim_3d(actor, context) -> None:
    if context.plugins is None or not context.plugins.enabled("bunnyland.3d"):
        return
    from bunnyland_3d import (
        ParticleSystem3D,
        VisualEffectDefinition,
        VisualEffectParticleLayer,
        VisualEffectStateRule,
        register_particle_systems,
        register_visual_effect_state_rules,
        register_visual_effects,
    )

    owner = "bunnyland.barbariansim"
    system_key = f"{owner}/poison-motes"
    effect_key = f"{owner}/poison"
    register_particle_systems(
        actor,
        owner,
        (
            ParticleSystem3D(
                system_key,
                vertical_motion="drift",
                vertical_scale=0.12,
                lateral_wobble=0.18,
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
                        count=22,
                        bounds=(0.7, 1.3, 0.7),
                        color="#50c878",
                        size=0.065,
                        speed=0.22,
                        opacity=0.76,
                    ),
                    VisualEffectParticleLayer(
                        system_key,
                        count=12,
                        bounds=(0.58, 1.1, 0.58),
                        color="#b8d936",
                        size=0.045,
                        speed=0.16,
                        opacity=0.68,
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
                f"{owner}/poison-state",
                PoisonComponent,
                lambda entity: entity.get_component(PoisonComponent).severity > 0,
                effect_key,
            ),
        ),
    )


__all__ = ["install_barbariansim_3d"]
