"""Tests for the imagegen plugin registration and pluggable prompt enhancers."""

from __future__ import annotations

from bunnyland.foundation.imagegen.plugin import plugin as imagegen_plugin
from bunnyland.imagegen.components import (
    EventImageComponent,
    ImageRequestComponent,
    PortraitImageComponent,
)
from bunnyland.imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
)
from bunnyland.imagegen.prompt import StubPromptEnhancer
from bunnyland.plugins import (
    ContentContribution,
    Plugin,
    collect_prompt_enhancers,
)
from bunnyland.plugins.ids import IMAGEGEN


def test_imagegen_plugin_registers_components_and_events():
    plugin = imagegen_plugin()
    assert plugin.id == IMAGEGEN
    assert plugin.default_enabled is True
    assert set(plugin.ecs.components) == {
        PortraitImageComponent,
        EventImageComponent,
        ImageRequestComponent,
    }
    assert set(plugin.commands.typed_events) == {
        ImageGenerationStartedEvent,
        ImageGenerationCompletedEvent,
        ImageGenerationFailedEvent,
    }


def test_collect_prompt_enhancers_gathers_from_plugins():
    enhancer = StubPromptEnhancer()
    plugin = Plugin(
        id="x.custom",
        name="Custom",
        content=ContentContribution(prompt_enhancers=(enhancer,)),
    )
    assert collect_prompt_enhancers([imagegen_plugin(), plugin]) == [enhancer]
