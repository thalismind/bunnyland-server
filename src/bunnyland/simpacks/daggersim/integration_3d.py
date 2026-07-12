"""Optional, lazily imported 3D healing spell effect."""

from .mechanics import SpellCastEvent


def install_daggersim_3d(actor, context) -> None:
    if context.plugins is None or not context.plugins.enabled("bunnyland.3d"):
        return
    from bunnyland_3d import (
        ParticleSystem3D,
        VisualEffectDefinition,
        VisualEffectParticleLayer,
        apply_visual_effect,
        register_particle_systems,
        register_visual_effects,
    )

    owner = "bunnyland.daggersim"
    gold_key = f"{owner}/healing-gold"
    blue_key = f"{owner}/healing-blue"
    effect_key = f"{owner}/healing"
    register_particle_systems(
        actor,
        owner,
        (
            ParticleSystem3D(gold_key, blending="additive", vertical_scale=0.65),
            ParticleSystem3D(
                blue_key,
                blending="additive",
                vertical_scale=0.5,
                lateral_wobble=0.04,
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
                        gold_key,
                        count=28,
                        bounds=(0.72, 1.45, 0.72),
                        color="#ffd45c",
                        size=0.075,
                        speed=0.58,
                        opacity=0.88,
                    ),
                    VisualEffectParticleLayer(
                        blue_key,
                        count=12,
                        bounds=(0.55, 1.25, 0.55),
                        color="#79c8ff",
                        size=0.045,
                        speed=0.42,
                        opacity=0.78,
                    ),
                ),
            ),
        ),
    )

    def on_spell_cast(event: SpellCastEvent) -> None:
        if event.effect_type == "heal":
            apply_visual_effect(actor, event.target_id, effect_key, 5, effect_key)

    actor.bus.subscribe(SpellCastEvent, on_spell_cast)


__all__ = ["install_daggersim_3d"]
