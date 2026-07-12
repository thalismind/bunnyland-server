from __future__ import annotations

import sys
from types import SimpleNamespace

from bunnyland.simpacks.barbariansim.integration_3d import install_barbariansim_3d
from bunnyland.simpacks.barbariansim.plugin import plugin as barbariansim_plugin
from bunnyland.simpacks.daggersim.integration_3d import install_daggersim_3d
from bunnyland.simpacks.daggersim.plugin import plugin as daggersim_plugin
from bunnyland.simpacks.voidsim.integration_3d import install_voidsim_3d
from bunnyland.simpacks.voidsim.plugin import plugin as voidsim_plugin


class _Value:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _Bus:
    def __init__(self):
        self.subscription = None

    def subscribe(self, event_type, callback):
        self.subscription = (event_type, callback)


def _context(enabled: bool):
    return SimpleNamespace(
        plugins=SimpleNamespace(enabled=lambda plugin_id: enabled and plugin_id == "bunnyland.3d")
    )


def _fake_3d():
    calls = SimpleNamespace(
        particles=[], definitions=[], rules=[], applications=[]
    )

    def record(name):
        def inner(_actor, owner, values):
            getattr(calls, name).append((owner, tuple(values)))

        return inner

    module = SimpleNamespace(
        ParticleSystem3D=_Value,
        VisualEffectDefinition=_Value,
        VisualEffectLightningLayer=_Value,
        VisualEffectParticleLayer=_Value,
        VisualEffectStateRule=_Value,
        register_particle_systems=record("particles"),
        register_visual_effects=record("definitions"),
        register_visual_effect_state_rules=record("rules"),
        apply_visual_effect=lambda *args: calls.applications.append(args),
    )
    return module, calls


def test_builtin_plugins_declare_lazy_3d_integrations():
    for definition, factory in (
        (barbariansim_plugin(), install_barbariansim_3d),
        (daggersim_plugin(), install_daggersim_3d),
        (voidsim_plugin(), install_voidsim_3d),
    ):
        assert "bunnyland.3d" in definition.dependencies.integrates_with
        assert factory in definition.runtime.integration_factories


def test_integrations_do_not_import_3d_when_addon_is_disabled():
    sys.modules.pop("bunnyland_3d", None)
    actor = SimpleNamespace()

    for factory in (
        install_barbariansim_3d,
        install_daggersim_3d,
        install_voidsim_3d,
    ):
        factory(actor, _context(False))

    assert "bunnyland_3d" not in sys.modules


def test_poison_and_chaos_register_state_effects(monkeypatch):
    fake, calls = _fake_3d()
    monkeypatch.setitem(sys.modules, "bunnyland_3d", fake)
    actor = SimpleNamespace()

    install_barbariansim_3d(actor, _context(True))
    install_voidsim_3d(actor, _context(True))

    assert [owner for owner, _values in calls.definitions] == [
        "bunnyland.barbariansim",
        "bunnyland.voidsim",
    ]
    poison_rule = calls.rules[0][1][0]
    chaos_rule = calls.rules[1][1][0]
    assert poison_rule.args[0] == "bunnyland.barbariansim/poison-state"
    poisoned = SimpleNamespace(
        get_component=lambda _type: SimpleNamespace(severity=1)
    )
    assert poison_rule.args[2](poisoned)
    assert chaos_rule.args[0] == "bunnyland.voidsim/chaos-state"
    chaos_definition = calls.definitions[1][1][0]
    assert chaos_definition.kwargs["lightning_layers"][0].kwargs["color"] == "#a020f0"


def test_successful_heal_applies_five_second_refreshable_effect(monkeypatch):
    fake, calls = _fake_3d()
    monkeypatch.setitem(sys.modules, "bunnyland_3d", fake)
    actor = SimpleNamespace(bus=_Bus())
    install_daggersim_3d(actor, _context(True))
    _event_type, callback = actor.bus.subscription

    callback(SimpleNamespace(effect_type="damage", target_id="entity_1"))
    callback(SimpleNamespace(effect_type="heal", target_id="entity_1"))

    assert calls.applications == [
        (
            actor,
            "entity_1",
            "bunnyland.daggersim/healing",
            5,
            "bunnyland.daggersim/healing",
        )
    ]
