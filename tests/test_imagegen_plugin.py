"""Tests for the imagegen plugin registration and pluggable prompt enhancers."""

from __future__ import annotations

from bunnyland.foundation.imagegen.plugin import plugin as imagegen_plugin
from bunnyland.imagegen.components import (
    EventImageComponent,
    EventVideoComponent,
    ImageRequestComponent,
    MediaSceneSnapshotComponent,
    PortraitImageComponent,
    VideoRequestComponent,
)
from bunnyland.imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
    ImageGenerationStartedEvent,
    VideoGenerationCompletedEvent,
    VideoGenerationFailedEvent,
    VideoGenerationStartedEvent,
)
from bunnyland.imagegen.prompt import StubPromptEnhancer
from bunnyland.plugins import (
    ContentContribution,
    Plugin,
    collect_image_prompt_enhancers,
    collect_media_fact_providers,
    collect_prompt_enhancers,
    collect_video_prompt_enhancers,
)
from bunnyland.plugins.ids import IMAGEGEN


def test_imagegen_plugin_registers_components_and_events():
    plugin = imagegen_plugin()
    assert plugin.id == IMAGEGEN
    assert plugin.default_enabled is True
    assert set(plugin.ecs.components) == {
        PortraitImageComponent,
        EventImageComponent,
        EventVideoComponent,
        ImageRequestComponent,
        VideoRequestComponent,
        MediaSceneSnapshotComponent,
    }
    assert set(plugin.commands.typed_events) == {
        ImageGenerationStartedEvent,
        ImageGenerationCompletedEvent,
        ImageGenerationFailedEvent,
        VideoGenerationStartedEvent,
        VideoGenerationCompletedEvent,
        VideoGenerationFailedEvent,
    }


def test_collect_prompt_enhancers_gathers_from_plugins():
    enhancer = StubPromptEnhancer()
    plugin = Plugin(
        id="x.custom",
        name="Custom",
        content=ContentContribution(prompt_enhancers=(enhancer,)),
    )
    assert collect_prompt_enhancers([imagegen_plugin(), plugin]) == [enhancer]


def test_collect_modality_enhancers_and_media_fact_providers():
    image_enhancer = object()
    video_enhancer = object()
    fact_provider = object()
    plugin = Plugin(
        id="x.media",
        name="Media",
        content=ContentContribution(
            image_prompt_enhancers=(image_enhancer,),
            video_prompt_enhancers=(video_enhancer,),
            media_fact_providers=(fact_provider,),
        ),
    )
    assert collect_image_prompt_enhancers([plugin]) == [image_enhancer]
    assert collect_video_prompt_enhancers([plugin]) == [video_enhancer]
    assert collect_media_fact_providers([plugin]) == [fact_provider]
