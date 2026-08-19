"""Provider-neutral image generator, plugin, and routing tests."""

from __future__ import annotations

import asyncio
import base64
import builtins
import io
import sys
import threading
from types import SimpleNamespace

import pytest
from conftest import build_scenario
from PIL import Image

from bunnyland.imagegen.comfyui import ComfyUIGenerator
from bunnyland.imagegen.components import PortraitImageComponent
from bunnyland.imagegen.config import (
    ComfyUIConfig,
    ImageGenConfig,
    MediaGenConfig,
    VideoGenConfig,
)
from bunnyland.imagegen.events import ImageGenerationCompletedEvent
from bunnyland.imagegen.generators import (
    ImageGeneratorProfile,
    ImageGeneratorRequest,
    VideoGeneratorProfile,
    collect_image_generators,
    collect_video_generators,
)
from bunnyland.imagegen.in_memory import InMemoryImageGenerator
from bunnyland.imagegen.media import MediaStore
from bunnyland.imagegen.openrouter import OpenRouterImageGenerator
from bunnyland.imagegen.prompt import (
    CatalogExampleSource,
    ImagePromptRequest,
    StubPromptEnhancer,
    VideoPromptRequest,
)
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.spec import GeneratedPrompt, ImagePurpose
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.wiring import build_media_services, select_enhancer
from bunnyland.plugins import ContentContribution, Plugin


class _ImageOnlyEnhancer:
    name = "image-only"

    async def enhance_image(self, request: ImagePromptRequest, *, examples=()):
        del examples
        return GeneratedPrompt(style=request.style, prompt=request.subject)


class _VideoOnlyEnhancer:
    name = "video-only"

    async def enhance_video(self, request: VideoPromptRequest, *, examples=()):
        del examples
        return GeneratedPrompt(style=request.style, prompt=request.subject)


class _SharedEnhancer(_ImageOnlyEnhancer, _VideoOnlyEnhancer):
    name = "shared"


def _request(**overrides) -> ImageGeneratorRequest:
    values = {
        "purpose": ImagePurpose.PORTRAIT,
        "prompt": "a silver rabbit in a red scarf",
        "negative": "blurry",
        "seed": 42,
        "width": 96,
        "height": 128,
        "profile_name": "portrait",
    }
    values.update(overrides)
    return ImageGeneratorRequest(**values)


def _media_config(
    generator: str = "in-memory",
    *,
    generators: dict[str, str] | None = None,
    media_root: str = "media",
    server_url: str = "",
    openrouter_image_model: str = "",
    openrouter_api_key: str = "",
    openrouter_server_url: str = "",
    openrouter_result_origins: tuple[str, ...] = (),
) -> MediaGenConfig:
    return MediaGenConfig(
        comfyui=ComfyUIConfig(server_url=server_url),
        image=ImageGenConfig(
            generator=generator,
            generators=generators or {},
            openrouter_image_model=openrouter_image_model,
            openrouter_api_key=openrouter_api_key,
            openrouter_server_url=openrouter_server_url,
            openrouter_result_origins=openrouter_result_origins,
        ),
        media_root=media_root,
    )


def _png(width: int = 8, height: int = 6, color=(12, 34, 56)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


async def test_in_memory_png_is_sized_deterministic_and_varies():
    generator = InMemoryImageGenerator()
    request = _request()
    first = await generator.generate(request)
    second = await generator.generate(request)
    changed_seed = await generator.generate(request.model_copy(update={"seed": 43}))
    changed_prompt = await generator.generate(request.model_copy(update={"prompt": "a fox"}))

    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert first == second
    assert first != changed_seed
    assert first != changed_prompt
    with Image.open(io.BytesIO(first)) as image:
        assert image.size == (96, 128)


async def test_in_memory_propagates_render_worker_failure(monkeypatch):
    import bunnyland.imagegen.in_memory as module

    def fail(*_args):
        raise RuntimeError("render failed")

    monkeypatch.setattr(module, "_render", fail)
    with pytest.raises(RuntimeError, match="render failed"):
        await module._render_off_loop("portrait", "rabbit", 1, 8, 8)


def test_in_memory_reports_missing_pillow(monkeypatch):
    import bunnyland.imagegen.in_memory as module

    original_import = builtins.__import__

    def missing_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_pillow)
    with pytest.raises(RuntimeError, match="requires the 'imagegen' extra"):
        module._load_pillow()


def test_in_memory_profiles_include_landscape_event():
    generator = InMemoryImageGenerator()
    event = generator.resolve_profile(ImagePurpose.EVENT)
    assert event.width > event.height
    with pytest.raises(ValueError, match="unknown image profile"):
        generator.resolve_profile(ImagePurpose.EVENT, "portrait")


async def test_in_memory_completes_service_job_with_provenance(tmp_path):
    scenario = build_scenario()
    events = []
    scenario.actor.bus.subscribe(ImageGenerationCompletedEvent, events.append)
    config = _media_config(media_root=str(tmp_path))
    service = build_media_services(scenario.actor, config).image
    assert service is not None

    job = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await service.wait_idle()

    portrait = scenario.actor.world.get_entity(scenario.character).get_component(
        PortraitImageComponent
    )
    assert job.status == "succeeded"
    assert job.generator == "in-memory"
    assert portrait.generator == "in-memory"
    assert portrait.template == "portrait"
    assert service.media.read("portraits", portrait.url.rsplit("/", 1)[-1]).startswith(
        b"\x89PNG"
    )
    assert events[-1].generator == "in-memory"
    await service.aclose()


class _Generator:
    def __init__(self, name: str) -> None:
        self.name = name
        self.requests = []

    def resolve_profile(self, purpose, profile_name=""):
        return ImageGeneratorProfile(name=profile_name or purpose.value, purpose=purpose)

    async def generate(self, request):
        self.requests.append(request)
        return _png()


class _Factory:
    name = "custom"

    def __init__(self) -> None:
        self.received = None

    def __call__(self, config, plugin_config):
        self.received = (config, plugin_config)
        return _Generator(self.name)


class _CreateFactory:
    name = "created"

    def create(self, config, plugin_config):
        return _Generator(self.name)


class _InvalidFactory:
    name = "broken"

    def __call__(self, config, plugin_config):
        return object()


class _MismatchFactory:
    name = "registered"

    def __call__(self, config, plugin_config):
        return _Generator("different")


class _VideoGenerator:
    def __init__(self, name: str) -> None:
        self.name = name

    def resolve_video_profile(self, profile_name=""):
        return VideoGeneratorProfile(name=profile_name or "event-video")

    async def generate_video(self, request):
        del request
        return b"video"


class _VideoFactory:
    name = "custom"

    def __init__(self) -> None:
        self.received = None

    def __call__(self, config, plugin_config):
        self.received = (config, plugin_config)
        return _VideoGenerator(self.name)


class _VideoCreateFactory:
    name = "created"

    def create(self, config, plugin_config):
        del config, plugin_config
        return _VideoGenerator(self.name)


class _InvalidVideoFactory:
    name = "broken"

    def __call__(self, config, plugin_config):
        del config, plugin_config
        return object()


class _MismatchVideoFactory:
    name = "registered"

    def __call__(self, config, plugin_config):
        del config, plugin_config
        return _VideoGenerator("different")


def test_collect_plugin_generator_receives_validated_owner_config():
    factory = _Factory()
    plugin = Plugin(
        id="example.images",
        name="Images",
        content=ContentContribution(image_generators=(factory,)),
    )
    config = _media_config("custom")
    result = collect_image_generators(
        [plugin], config, {"example.images": {"palette": "warm"}}
    )
    assert result["custom"].name == "custom"
    assert factory.received == (config, {"palette": "warm"})


def test_collect_plugin_generators_rejects_duplicates():
    first = Plugin(
        id="example.first",
        name="First",
        content=ContentContribution(image_generators=(_Factory(),)),
    )
    second = Plugin(
        id="example.second",
        name="Second",
        content=ContentContribution(image_generators=(_Factory(),)),
    )
    with pytest.raises(ValueError, match="duplicate image generator"):
        collect_image_generators([first, second], _media_config("custom"))


@pytest.mark.parametrize(
    ("factory", "error", "message"),
    [
        (object(), ValueError, "has no name"),
        (_InvalidFactory(), TypeError, "invalid generator"),
    ],
)
def test_collect_plugin_generators_rejects_invalid_factories(factory, error, message):
    plugin = Plugin(
        id="example.invalid",
        name="Invalid",
        content=ContentContribution(image_generators=(factory,)),
    )
    with pytest.raises(error, match=message):
        collect_image_generators([plugin], _media_config())


def test_collect_plugin_generators_supports_create_and_rejects_name_mismatch():
    created = Plugin(
        id="example.created",
        name="Created",
        content=ContentContribution(image_generators=(_CreateFactory(),)),
    )
    assert collect_image_generators([created], _media_config())["created"].name == "created"

    mismatch = Plugin(
        id="example.mismatch",
        name="Mismatch",
        content=ContentContribution(image_generators=(_MismatchFactory(),)),
    )
    with pytest.raises(ValueError, match="returned generator 'different'"):
        collect_image_generators([mismatch], _media_config())


def test_public_plugin_collector_delegates():
    from bunnyland.plugins import collect_image_generators as public_collect

    plugin = Plugin(
        id="example.images",
        name="Images",
        content=ContentContribution(image_generators=(_Factory(),)),
    )
    assert public_collect([plugin], _media_config())["custom"].name == "custom"


def test_collect_plugin_video_generator_receives_owner_config_and_public_delegates():
    from bunnyland.plugins import collect_video_generators as public_collect

    factory = _VideoFactory()
    plugin = Plugin(
        id="example.video",
        name="Video",
        content=ContentContribution(video_generators=(factory,)),
    )
    config = _media_config()
    result = collect_video_generators(
        [plugin], config, {"example.video": {"model": "seedance"}}
    )
    assert result["custom"].name == "custom"
    assert factory.received == (config, {"model": "seedance"})
    assert public_collect([plugin], config)["custom"].name == "custom"


def test_collect_plugin_video_generators_support_create_and_reject_invalid_contracts():
    created = Plugin(
        id="example.created-video",
        name="Created Video",
        content=ContentContribution(video_generators=(_VideoCreateFactory(),)),
    )
    assert collect_video_generators([created], _media_config())["created"].name == "created"

    cases = [
        (object(), ValueError, "has no name"),
        (_InvalidVideoFactory(), TypeError, "invalid generator"),
        (_MismatchVideoFactory(), ValueError, "returned generator 'different'"),
    ]
    for factory, error, message in cases:
        plugin = Plugin(
            id=f"example.{type(factory).__name__}",
            name="Invalid Video",
            content=ContentContribution(video_generators=(factory,)),
        )
        with pytest.raises(error, match=message):
            collect_video_generators([plugin], _media_config())


def test_collect_plugin_video_generators_reject_duplicates_but_namespaces_are_independent():
    first_factory = _VideoFactory()
    second_factory = _VideoFactory()
    first = Plugin(
        id="example.first-video",
        name="First Video",
        content=ContentContribution(video_generators=(first_factory,)),
    )
    second = Plugin(
        id="example.second-video",
        name="Second Video",
        content=ContentContribution(video_generators=(second_factory,)),
    )
    with pytest.raises(ValueError, match="duplicate video generator"):
        collect_video_generators([first, second], _media_config())

    dual = Plugin(
        id="example.dual",
        name="Dual",
        content=ContentContribution(
            image_generators=(_Factory(),), video_generators=(_VideoFactory(),)
        ),
    )
    assert collect_image_generators([dual], _media_config())["custom"].name == "custom"
    assert collect_video_generators([dual], _media_config())["custom"].name == "custom"


def test_wiring_applies_fallback_and_all_purpose_overrides(tmp_path):
    scenario = build_scenario()
    custom = _Factory()
    plugin = Plugin(
        id="example.images",
        name="Images",
        content=ContentContribution(image_generators=(custom,)),
    )
    config = _media_config(
        "in-memory",
        generators={
            "portrait": "custom",
            "entity": "in-memory",
            "sprite": "custom",
            "event": "in-memory",
        },
        media_root=str(tmp_path),
    )
    service = build_media_services(scenario.actor, config, plugins=[plugin]).image
    assert service is not None
    assert service._generators[ImagePurpose.PORTRAIT].name == "custom"
    assert service._generators[ImagePurpose.ENTITY].name == "in-memory"
    assert service._generators[ImagePurpose.SPRITE].name == "custom"
    assert service._generators[ImagePurpose.EVENT].name == "in-memory"


def test_wiring_rejects_unknown_generator():
    with pytest.raises(ValueError, match="unknown image generator 'ghost'"):
        build_media_services(build_scenario().actor, _media_config("ghost"))


def test_wiring_rejects_duplicate_builtin_and_missing_comfy_url():
    duplicate = _Factory()
    duplicate.name = "comfyui"
    plugin = Plugin(
        id="example.comfy",
        name="Comfy",
        content=ContentContribution(image_generators=(duplicate,)),
    )
    with pytest.raises(ValueError, match="duplicate image generator 'comfyui'"):
        build_media_services(
            build_scenario().actor,
            _media_config(),
            plugins=[plugin],
        )
    with pytest.raises(ValueError, match="requires COMFYUI_SERVER_URL"):
        build_media_services(build_scenario().actor, _media_config("comfyui"))


def test_wiring_constructs_selected_openrouter(monkeypatch, tmp_path):
    import bunnyland.imagegen.wiring as wiring

    constructed = {}

    class FakeOpenRouter(_Generator):
        def __init__(self, **kwargs):
            super().__init__("openrouter")
            constructed.update(kwargs)

    monkeypatch.setattr(wiring, "OpenRouterImageGenerator", FakeOpenRouter)
    config = _media_config(
        "openrouter",
        openrouter_image_model="example/image",
        openrouter_api_key="secret",
        openrouter_server_url="https://router.example",
        openrouter_result_origins=("https://cdn.example",),
        media_root=str(tmp_path),
    )
    service = build_media_services(build_scenario().actor, config).image
    assert service is not None
    assert service._generators[ImagePurpose.EVENT].name == "openrouter"
    assert constructed == {
        "model": "example/image",
        "api_key": "secret",
        "server_url": "https://router.example",
        "allowed_result_origins": ("https://cdn.example",),
    }


def test_wiring_validates_independent_video_registry_and_partial_image_routes(tmp_path):
    actor = build_scenario().actor
    partial = MediaGenConfig(
        image=ImageGenConfig(generators={"portrait": "in-memory"}),
        media_root=str(tmp_path),
    )
    with pytest.raises(ValueError, match="generator for every image purpose"):
        build_media_services(actor, partial)

    unknown = MediaGenConfig(
        video=VideoGenConfig(generator="seedance", profile="event-video"),
        media_root=str(tmp_path),
    )
    with pytest.raises(ValueError, match="unknown video generator 'seedance'"):
        build_media_services(actor, unknown)

    duplicate = _VideoFactory()
    duplicate.name = "comfyui"
    plugin = Plugin(
        id="example.comfy-video",
        name="Comfy Video",
        content=ContentContribution(video_generators=(duplicate,)),
    )
    duplicate_config = MediaGenConfig(
        comfyui=ComfyUIConfig(server_url="http://comfy.local"),
        video=VideoGenConfig(generator="comfyui", profile="event-video"),
        media_root=str(tmp_path),
    )
    with pytest.raises(ValueError, match="duplicate video generator 'comfyui'"):
        build_media_services(actor, duplicate_config, plugins=[plugin])


def test_wiring_supports_plugin_video_without_image_service(tmp_path):
    factory = _VideoFactory()
    factory.name = "seedance"
    plugin = Plugin(
        id="example.seedance",
        name="Seedance",
        content=ContentContribution(video_generators=(factory,)),
    )
    config = MediaGenConfig(
        video=VideoGenConfig(generator="seedance", profile="cinematic"),
        media_root=str(tmp_path),
    )
    services = build_media_services(actor := build_scenario().actor, config, plugins=[plugin])
    assert services.image is None
    assert services.backfill is None
    assert services.video is not None
    assert services.video._generator.name == "seedance"
    assert actor.media_service is services.media


def test_wiring_selects_independent_modality_prompt_enhancers(tmp_path):
    video_factory = _VideoFactory()
    video_factory.name = "seedance"
    image_enhancer = _ImageOnlyEnhancer()
    video_enhancer = _VideoOnlyEnhancer()
    plugin = Plugin(
        id="example.media-adapters",
        name="Media adapters",
        content=ContentContribution(
            image_prompt_enhancers=(image_enhancer,),
            video_prompt_enhancers=(video_enhancer,),
            video_generators=(video_factory,),
        ),
    )
    config = MediaGenConfig(
        image=ImageGenConfig(
            generator="in-memory",
            prompt_enhancer="image-only",
        ),
        video=VideoGenConfig(
            generator="seedance",
            profile="cinematic",
            prompt_enhancer="video-only",
        ),
        media_root=str(tmp_path),
    )
    services = build_media_services(build_scenario().actor, config, plugins=[plugin])
    assert services.image is not None and services.image._enhancer is image_enhancer
    assert services.video is not None and services.video._enhancer is video_enhancer


@pytest.mark.parametrize(
    ("field", "name", "message"),
    (
        ("image", "bad-image", "invalid contract"),
        ("image", "missing", "unknown image prompt enhancer"),
        ("video", "bad-video", "invalid contract"),
        ("video", "missing", "unknown video prompt enhancer"),
    ),
)
def test_wiring_rejects_invalid_or_unknown_modality_enhancers(
    tmp_path, field, name, message
):
    video_factory = _VideoFactory()
    video_factory.name = "seedance"
    invalid = SimpleNamespace(name=name)
    plugin = Plugin(
        id="example.bad-enhancer",
        name="Bad enhancer",
        content=ContentContribution(
            image_prompt_enhancers=(invalid,)
            if field == "image" and name.startswith("bad")
            else (),
            video_prompt_enhancers=(invalid,)
            if field == "video" and name.startswith("bad")
            else (),
            video_generators=(video_factory,),
        ),
    )
    config = MediaGenConfig(
        image=ImageGenConfig(
            generator="in-memory",
            prompt_enhancer=name if field == "image" else "",
        ),
        video=VideoGenConfig(
            generator="seedance",
            profile="cinematic",
            prompt_enhancer=name if field == "video" else "",
        ),
        media_root=str(tmp_path),
    )
    with pytest.raises((TypeError, ValueError), match=message):
        build_media_services(build_scenario().actor, config, plugins=[plugin])


def test_wiring_reuses_shared_builtin_enhancer_and_rejects_bad_fact_provider(tmp_path):
    shared = build_media_services(
        build_scenario().actor,
        MediaGenConfig(
            image=ImageGenConfig(
                generator="in-memory",
                prompt_enhancer="stub",
            ),
            enhancer="stub",
            media_root=str(tmp_path),
        ),
    )
    assert shared.image is not None and shared.image._enhancer.name == "stub"

    independent_builtins = build_media_services(
        build_scenario().actor,
        MediaGenConfig(
            image=ImageGenConfig(
                generator="in-memory",
                prompt_enhancer="stub",
            ),
            video=VideoGenConfig(
                generator="",
                prompt_enhancer="structured",
            ),
            enhancer="",
            media_root=str(tmp_path / "independent"),
        ),
    )
    assert independent_builtins.image is not None
    assert independent_builtins.image._enhancer.name == "stub"

    plugin = Plugin(
        id="example.bad-facts",
        name="Bad facts",
        content=ContentContribution(media_fact_providers=(object(),)),
    )
    with pytest.raises(TypeError, match="media fact providers"):
        build_media_services(
            build_scenario().actor,
            _media_config("in-memory", media_root=str(tmp_path)),
            plugins=[plugin],
        )


def test_wiring_skips_nonmatching_plugin_enhancers_for_each_modality(tmp_path):
    image_enhancer = _ImageOnlyEnhancer()
    video_enhancer = _VideoOnlyEnhancer()
    video_factory = _VideoFactory()
    video_factory.name = "seedance"
    plugin = Plugin(
        id="example.prompt-order",
        name="Prompt ordering",
        content=ContentContribution(
            image_prompt_enhancers=(SimpleNamespace(name="other-image"), image_enhancer),
            video_prompt_enhancers=(SimpleNamespace(name="other-video"), video_enhancer),
            video_generators=(video_factory,),
        ),
    )
    services = build_media_services(
        build_scenario().actor,
        MediaGenConfig(
            image=ImageGenConfig(
                generator="in-memory",
                prompt_enhancer="image-only",
                ),
                video=VideoGenConfig(
                    generator="seedance",
                prompt_enhancer="video-only",
            ),
            media_root=str(tmp_path),
        ),
        plugins=[plugin],
    )
    assert services.image is not None and services.image._enhancer is image_enhancer
    assert services.video is not None and services.video._enhancer is video_enhancer


def test_wiring_selects_legacy_shared_and_llm_enhancers(tmp_path, monkeypatch):
    shared = _SharedEnhancer()
    video_factory = _VideoFactory()
    video_factory.name = "seedance"
    plugin = Plugin(
        id="example.shared-prompt",
        name="Shared prompt",
        content=ContentContribution(
            prompt_enhancers=(SimpleNamespace(name="other"), shared),
            video_generators=(video_factory,),
        ),
    )
    assert select_enhancer(MediaGenConfig(), plugins=[plugin]).name == "structured"
    assert select_enhancer(MediaGenConfig(enhancer="stub"), plugins=[plugin]).name == "stub"
    assert select_enhancer(MediaGenConfig(enhancer="shared"), plugins=[plugin]) is shared
    with pytest.raises(ValueError, match="unknown media enhancer"):
        select_enhancer(MediaGenConfig(enhancer="missing"), plugins=[plugin])

    captured = {}

    def fake_llm(**options):
        captured.update(options)
        return shared

    monkeypatch.setattr("bunnyland.imagegen.wiring.LLMPromptEnhancer", fake_llm)
    assert select_enhancer(
        MediaGenConfig(
            enhancer="llm",
            model="media-model",
            host="https://ollama.example",
            api_key="secret",
        )
    ) is shared
    assert captured == {
        "model": "media-model",
        "host": "https://ollama.example",
        "api_key": "secret",
    }

    services = build_media_services(
        build_scenario().actor,
        MediaGenConfig(
            video=VideoGenConfig(
                generator="seedance",
                prompt_enhancer="shared",
            ),
            enhancer="shared",
            media_root=str(tmp_path),
        ),
        plugins=[plugin],
    )
    assert services.video is not None and services.video._enhancer is shared


def test_comfy_generator_rejects_profile_for_another_purpose():
    store = WorkflowTemplateStore(defaults=default_templates())
    generator = ComfyUIGenerator(SimpleNamespace(), store)
    with pytest.raises(ValueError, match="does not support purpose 'portrait'"):
        generator.resolve_profile(ImagePurpose.PORTRAIT, "event")


def test_service_requires_explicit_generators(tmp_path):
    with pytest.raises(TypeError, match="generators"):
        ImageGenService(
            build_scenario().actor,
            _media_config(),
            enhancer=StubPromptEnhancer(),
            examples=CatalogExampleSource(),
            media=MediaStore(tmp_path),
        )


class _Chat:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    async def send_async(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _openrouter_response(value: str | None = None, *, refusal: str = ""):
    images = []
    if value is not None:
        images.append(SimpleNamespace(image_url=SimpleNamespace(url=value)))
    message = SimpleNamespace(images=images, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


async def test_openrouter_uses_async_image_modality_and_data_url():
    value = "data:image/png;base64," + base64.b64encode(_png()).decode()
    chat = _Chat(_openrouter_response(value))
    generator = OpenRouterImageGenerator(
        model="example/image", api_key="secret", client=SimpleNamespace(chat=chat)
    )
    result = await generator.generate(_request())
    call = chat.calls[0]
    assert result.startswith(b"\x89PNG")
    assert call["model"] == "example/image"
    assert call["modalities"] == ["image"]
    assert call["seed"] == 42
    assert call["image_config"] == {"aspect_ratio": "2:3", "output_format": "png"}
    assert "Avoid these elements: blurry" in call["messages"][0]["content"]


async def test_openrouter_supports_dict_responses_empty_negative_and_square_output():
    value = "data:image/png;base64," + base64.b64encode(_png()).decode()
    response = {"choices": [{"message": {"images": [{"image_url": {"url": value}}]}}]}
    chat = _Chat(response)
    generator = OpenRouterImageGenerator(
        model="example/image", api_key="secret", client=SimpleNamespace(chat=chat)
    )
    await generator.generate(_request(negative="", width=64, height=64))
    call = chat.calls[0]
    assert call["messages"][0]["content"] == _request().prompt
    assert call["image_config"]["aspect_ratio"] == "1:1"


def test_openrouter_constructs_official_sdk_client(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "openrouter", SimpleNamespace(OpenRouter=FakeClient))
    OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        server_url="https://router.example",
    )
    OpenRouterImageGenerator(model="example/image", api_key="secret")
    assert calls == [
        {"api_key": "secret", "server_url": "https://router.example"},
        {"api_key": "secret"},
    ]


def test_openrouter_reports_missing_sdk(monkeypatch):
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name == "openrouter":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)
    with pytest.raises(RuntimeError, match="requires the 'llm' extra"):
        OpenRouterImageGenerator(model="example/image", api_key="secret")


class _HttpResponse:
    content = _png(color=(90, 80, 70))
    headers: dict[str, str] = {}

    def __init__(self, *, chunks=None, headers=None) -> None:
        self._chunks = list(chunks) if chunks is not None else [self.content]
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _Http:
    def __init__(self) -> None:
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url):
        assert method == "GET"
        self.urls.append(url)
        return _HttpResponse()


async def test_openrouter_fetches_https_and_normalizes_png():
    http = _Http()
    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://cdn.example/image"))),
        http_factory=lambda: http,
        allowed_result_origins=("https://cdn.example",),
    )
    assert (await generator.generate(_request())).startswith(b"\x89PNG")
    assert http.urls == ["https://cdn.example/image"]


async def test_openrouter_uses_default_http_client(monkeypatch):
    http = _Http()
    timeouts = []

    def async_client(*, timeout):
        timeouts.append(timeout)
        return http

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=async_client))
    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://cdn.example/image"))),
        allowed_result_origins=("https://cdn.example",),
    )
    await generator.generate(_request())
    assert timeouts == [120.0]


async def test_openrouter_rejects_private_result_addresses():
    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(
            chat=_Chat(_openrouter_response("https://127.0.0.1/private.png"))
        ),
        http_factory=_Http,
        allowed_result_origins=("https://127.0.0.1",),
    )

    with pytest.raises(RuntimeError, match="non-public address"):
        await generator.generate(_request())


async def test_openrouter_rejects_https_origins_that_are_not_allowlisted():
    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://other.example/image"))),
        http_factory=_Http,
        allowed_result_origins=("https://cdn.example",),
    )

    with pytest.raises(RuntimeError, match="origin is not explicitly allowed"):
        await generator.generate(_request())


async def test_openrouter_bounds_data_and_https_results(monkeypatch):
    import bunnyland.imagegen.openrouter as openrouter_module

    monkeypatch.setattr(openrouter_module, "MAX_OPENROUTER_IMAGE_BYTES", 2)
    encoded = base64.b64encode(b"oversized").decode()
    data_generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(
            chat=_Chat(_openrouter_response(f"data:image/png;base64,{encoded}"))
        ),
    )
    with pytest.raises(RuntimeError, match="malformed image data URL"):
        await data_generator.generate(_request())

    https_generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://cdn.example/image"))),
        http_factory=_Http,
        allowed_result_origins=("https://cdn.example",),
    )
    with pytest.raises(RuntimeError, match="exceeds 20 MiB"):
        await https_generator.generate(_request())


async def test_openrouter_bounds_decoded_data_and_declared_https_length(monkeypatch):
    import bunnyland.imagegen.openrouter as module

    monkeypatch.setattr(module, "MAX_OPENROUTER_IMAGE_BYTES", 4)
    encoded = base64.b64encode(b"12345").decode()
    data_generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(
            chat=_Chat(_openrouter_response(f"data:image/png;base64,{encoded}"))
        ),
    )
    with pytest.raises(RuntimeError, match="malformed image data URL"):
        await data_generator.generate(_request())

    class LengthHttp(_Http):
        def stream(self, method, url):
            assert method == "GET"
            self.urls.append(url)
            return _HttpResponse(headers={"content-length": "5"}, chunks=[])

    https_generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://cdn.example/image"))),
        http_factory=LengthHttp,
        allowed_result_origins=("https://cdn.example",),
    )
    with pytest.raises(RuntimeError, match="exceeds 20 MiB"):
        await https_generator.generate(_request())


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (SimpleNamespace(choices=[]), "image-less"),
        (_openrouter_response(), "image-less"),
        (_openrouter_response("", refusal="policy"), "refused"),
        (
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            images=[SimpleNamespace(image_url=SimpleNamespace(url=None))],
                            refusal="",
                        )
                    )
                ]
            ),
            "malformed image result",
        ),
        (_openrouter_response("not-a-url"), "data URL or HTTPS"),
        (_openrouter_response("data:image/png,raw"), "malformed image data URL"),
        (_openrouter_response("data:image/png;base64,%%%"), "malformed image data URL"),
    ],
)
async def test_openrouter_rejects_refusal_and_malformed_results(response, message):
    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(response)),
    )
    with pytest.raises(RuntimeError, match=message):
        await generator.generate(_request())


async def test_openrouter_wraps_sdk_errors():
    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(error=ValueError("provider down"))),
    )
    with pytest.raises(RuntimeError, match="OpenRouter image generation failed: provider down"):
        await generator.generate(_request())


async def test_openrouter_wraps_https_errors():
    class FailedHttp(_Http):
        def stream(self, method, url):
            raise OSError("cdn down")

    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://cdn.example/image"))),
        http_factory=FailedHttp,
        allowed_result_origins=("https://cdn.example",),
    )
    with pytest.raises(RuntimeError, match="failed to fetch.*cdn down"):
        await generator.generate(_request())


def test_openrouter_rejects_unknown_profile():
    generator = OpenRouterImageGenerator(
        model="example/image", api_key="secret", client=SimpleNamespace(chat=_Chat())
    )
    with pytest.raises(ValueError, match="unknown image profile"):
        generator.resolve_profile(ImagePurpose.EVENT, "portrait")
    assert generator.resolve_profile(ImagePurpose.EVENT).name == "event"
    assert generator.resolve_profile(ImagePurpose.EVENT, "event").purpose is ImagePurpose.EVENT


def test_openrouter_rejects_invalid_raster():
    import bunnyland.imagegen.openrouter as module

    with pytest.raises(RuntimeError, match="invalid raster image data"):
        module._normalize_png(b"not an image")


def test_openrouter_validates_result_hosts_origins_and_content_lengths():
    import bunnyland.imagegen.openrouter as module

    with pytest.raises(RuntimeError, match="no hostname"):
        module._reject_nonpublic_literal_host("https:///image.png")
    module._reject_nonpublic_literal_host("https://8.8.8.8/image.png")

    for origin in ("http://cdn.example", "https:///image.png"):
        with pytest.raises(ValueError, match="must be HTTPS"):
            module._https_origin(origin)
    with pytest.raises(ValueError, match="must not contain credentials"):
        module._https_origin("https://user:secret@cdn.example")
    with pytest.raises(ValueError, match="invalid port"):
        module._https_origin("https://cdn.example:not-a-port")
    assert module._https_origin("https://[2001:4860:4860::8888]:443/path") == (
        "https://[2001:4860:4860::8888]"
    )
    assert module._https_origin("https://cdn.example:8443/path") == (
        "https://cdn.example:8443"
    )

    assert module._content_length({}) is None
    assert module._content_length({"Content-Length": "12"}) == 12
    assert module._content_length({"content-length": "invalid"}) is None
    assert module._content_length({"content-length": "-1"}) == 0


def test_openrouter_rejects_excessive_pixel_dimensions(monkeypatch):
    import bunnyland.imagegen.openrouter as module

    monkeypatch.setattr(module, "MAX_OPENROUTER_IMAGE_PIXELS", 1)
    with pytest.raises(RuntimeError, match="invalid raster image data"):
        module._normalize_png(_png())


async def test_openrouter_propagates_normalization_worker_failure(monkeypatch):
    import bunnyland.imagegen.openrouter as module

    def fail(_data):
        raise RuntimeError("normalize failed")

    monkeypatch.setattr(module, "_normalize_png", fail)
    with pytest.raises(RuntimeError, match="normalize failed"):
        await module._normalize_off_loop(b"data")


async def test_openrouter_normalization_waits_for_worker_without_blocking_loop(monkeypatch):
    import bunnyland.imagegen.openrouter as module

    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def normalize(data: bytes) -> bytes:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=1)
        return data + b"-normalized"

    monkeypatch.setattr(module, "_normalize_png", normalize)
    task = asyncio.create_task(module._normalize_off_loop(b"data"))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
    finally:
        release.set()

    assert await task == b"data-normalized"


def test_openrouter_reports_missing_pillow(monkeypatch):
    import bunnyland.imagegen.openrouter as module

    original_import = builtins.__import__

    def missing_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_pillow)
    with pytest.raises(RuntimeError, match="requires the 'imagegen' extra"):
        module._load_pillow()


def test_openrouter_requires_model_and_credentials():
    client = SimpleNamespace(chat=_Chat())
    with pytest.raises(ValueError, match="BUNNYLAND_IMAGE_OPENROUTER_MODEL"):
        OpenRouterImageGenerator(model="", api_key="secret", client=client)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterImageGenerator(model="example/image", api_key="", client=client)


def test_config_environment_activation_and_overrides():
    enabled = MediaGenConfig.from_env({"BUNNYLAND_IMAGE_GENERATOR": "in-memory"})
    assert enabled is not None
    assert enabled.image.generator == "in-memory"
    config = MediaGenConfig.from_env(
        {
            "BUNNYLAND_IMAGE_GENERATOR": "in-memory",
            "BUNNYLAND_IMAGE_GENERATOR_PORTRAIT": "openrouter",
            "BUNNYLAND_IMAGE_GENERATOR_ENTITY": "comfyui",
            "BUNNYLAND_IMAGE_GENERATOR_SPRITE": "in-memory",
            "BUNNYLAND_IMAGE_GENERATOR_EVENT": "openrouter",
            "BUNNYLAND_IMAGE_OPENROUTER_MODEL": "example/image",
            "BUNNYLAND_IMAGE_OPENROUTER_RESULT_ORIGINS": (
                "https://cdn-a.example, https://cdn-b.example"
            ),
            "OPENROUTER_API_KEY": "secret",
        }
    )
    assert config is not None
    assert config.image.generator_for("portrait") == "openrouter"
    assert config.image.generator_for("entity") == "comfyui"
    assert config.image.generator_for("sprite") == "in-memory"
    assert config.image.generator_for("event") == "openrouter"
    assert config.image.openrouter_image_model == "example/image"
    assert config.image.openrouter_api_key == "secret"
    assert config.image.openrouter_result_origins == (
        "https://cdn-a.example",
        "https://cdn-b.example",
    )
