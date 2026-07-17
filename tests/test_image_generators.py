"""Provider-neutral image generator, plugin, and routing tests."""

from __future__ import annotations

import base64
import builtins
import io
import sys
from types import SimpleNamespace

import pytest
from conftest import build_scenario
from PIL import Image

from bunnyland.imagegen.comfyui import ComfyUIImageGenerator
from bunnyland.imagegen.components import PortraitImageComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.events import ImageGenerationCompletedEvent
from bunnyland.imagegen.generators import (
    ImageGeneratorProfile,
    ImageGeneratorRequest,
    collect_image_generators,
)
from bunnyland.imagegen.in_memory import InMemoryImageGenerator
from bunnyland.imagegen.media import MediaStore
from bunnyland.imagegen.openrouter import OpenRouterImageGenerator
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.wiring import build_image_service
from bunnyland.plugins import ContentContribution, Plugin


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
    config = ImageGenConfig(generator="in-memory", media_root=str(tmp_path))
    service = build_image_service(scenario.actor, config)

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


def test_collect_plugin_generator_receives_validated_owner_config():
    factory = _Factory()
    plugin = Plugin(
        id="example.images",
        name="Images",
        content=ContentContribution(image_generators=(factory,)),
    )
    config = ImageGenConfig(generator="custom")
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
        collect_image_generators([first, second], ImageGenConfig(generator="custom"))


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
        collect_image_generators([plugin], ImageGenConfig(generator="in-memory"))


def test_collect_plugin_generators_supports_create_and_rejects_name_mismatch():
    created = Plugin(
        id="example.created",
        name="Created",
        content=ContentContribution(image_generators=(_CreateFactory(),)),
    )
    assert collect_image_generators([created], ImageGenConfig())["created"].name == "created"

    mismatch = Plugin(
        id="example.mismatch",
        name="Mismatch",
        content=ContentContribution(image_generators=(_MismatchFactory(),)),
    )
    with pytest.raises(ValueError, match="returned generator 'different'"):
        collect_image_generators([mismatch], ImageGenConfig())


def test_public_plugin_collector_delegates():
    from bunnyland.plugins import collect_image_generators as public_collect

    plugin = Plugin(
        id="example.images",
        name="Images",
        content=ContentContribution(image_generators=(_Factory(),)),
    )
    assert public_collect([plugin], ImageGenConfig())["custom"].name == "custom"


def test_wiring_applies_fallback_and_all_purpose_overrides(tmp_path):
    scenario = build_scenario()
    custom = _Factory()
    plugin = Plugin(
        id="example.images",
        name="Images",
        content=ContentContribution(image_generators=(custom,)),
    )
    config = ImageGenConfig(
        generator="in-memory",
        generators={
            "portrait": "custom",
            "entity": "in-memory",
            "sprite": "custom",
            "event": "in-memory",
        },
        media_root=str(tmp_path),
    )
    service = build_image_service(scenario.actor, config, plugins=[plugin])
    assert service._generators[ImagePurpose.PORTRAIT].name == "custom"
    assert service._generators[ImagePurpose.ENTITY].name == "in-memory"
    assert service._generators[ImagePurpose.SPRITE].name == "custom"
    assert service._generators[ImagePurpose.EVENT].name == "in-memory"


def test_wiring_rejects_unknown_generator():
    with pytest.raises(ValueError, match="unknown image generator 'ghost'"):
        build_image_service(build_scenario().actor, ImageGenConfig(generator="ghost"))


def test_wiring_rejects_duplicate_builtin_and_missing_comfy_url():
    duplicate = _Factory()
    duplicate.name = "comfyui"
    plugin = Plugin(
        id="example.comfy",
        name="Comfy",
        content=ContentContribution(image_generators=(duplicate,)),
    )
    with pytest.raises(ValueError, match="duplicate image generator 'comfyui'"):
        build_image_service(
            build_scenario().actor,
            ImageGenConfig(generator="in-memory"),
            plugins=[plugin],
        )
    with pytest.raises(ValueError, match="requires COMFYUI_SERVER_URL"):
        build_image_service(build_scenario().actor, ImageGenConfig(generator="comfyui"))


def test_wiring_constructs_selected_openrouter(monkeypatch, tmp_path):
    import bunnyland.imagegen.wiring as wiring

    constructed = {}

    class FakeOpenRouter(_Generator):
        def __init__(self, **kwargs):
            super().__init__("openrouter")
            constructed.update(kwargs)

    monkeypatch.setattr(wiring, "OpenRouterImageGenerator", FakeOpenRouter)
    config = ImageGenConfig(
        generator="openrouter",
        openrouter_image_model="example/image",
        openrouter_api_key="secret",
        openrouter_server_url="https://router.example",
        media_root=str(tmp_path),
    )
    service = build_image_service(build_scenario().actor, config)
    assert service._generators[ImagePurpose.EVENT].name == "openrouter"
    assert constructed == {
        "model": "example/image",
        "api_key": "secret",
        "server_url": "https://router.example",
    }


def test_comfy_generator_rejects_profile_for_another_purpose():
    store = WorkflowTemplateStore(defaults=default_templates())
    generator = ComfyUIImageGenerator(SimpleNamespace(), store)
    with pytest.raises(ValueError, match="does not support purpose 'portrait'"):
        generator.resolve_profile(ImagePurpose.PORTRAIT, "event")


def test_service_requires_a_generator_or_legacy_comfy_dependencies(tmp_path):
    with pytest.raises(TypeError, match="requires generators or a ComfyUI client/templates"):
        ImageGenService(
            build_scenario().actor,
            ImageGenConfig(generator="in-memory"),
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

    def raise_for_status(self):
        return None


class _Http:
    def __init__(self) -> None:
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        self.urls.append(url)
        return _HttpResponse()


async def test_openrouter_fetches_https_and_normalizes_png():
    http = _Http()
    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://cdn.example/image"))),
        http_factory=lambda: http,
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
    )
    await generator.generate(_request())
    assert timeouts == [120.0]


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
        async def get(self, url):
            raise OSError("cdn down")

    generator = OpenRouterImageGenerator(
        model="example/image",
        api_key="secret",
        client=SimpleNamespace(chat=_Chat(_openrouter_response("https://cdn.example/image"))),
        http_factory=FailedHttp,
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


async def test_openrouter_propagates_normalization_worker_failure(monkeypatch):
    import bunnyland.imagegen.openrouter as module

    def fail(_data):
        raise RuntimeError("normalize failed")

    monkeypatch.setattr(module, "_normalize_png", fail)
    with pytest.raises(RuntimeError, match="normalize failed"):
        await module._normalize_off_loop(b"data")


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
    assert ImageGenConfig.from_env({"BUNNYLAND_IMAGE_GENERATOR": "in-memory"}).generator == (
        "in-memory"
    )
    config = ImageGenConfig.from_env(
        {
            "BUNNYLAND_IMAGE_GENERATOR": "in-memory",
            "BUNNYLAND_IMAGE_GENERATOR_PORTRAIT": "openrouter",
            "BUNNYLAND_IMAGE_GENERATOR_ENTITY": "comfyui",
            "BUNNYLAND_IMAGE_GENERATOR_SPRITE": "in-memory",
            "BUNNYLAND_IMAGE_GENERATOR_EVENT": "openrouter",
            "BUNNYLAND_IMAGE_OPENROUTER_MODEL": "example/image",
            "OPENROUTER_API_KEY": "secret",
        }
    )
    assert config.generator_for("portrait") == "openrouter"
    assert config.generator_for("entity") == "comfyui"
    assert config.generator_for("sprite") == "in-memory"
    assert config.generator_for("event") == "openrouter"
    assert config.openrouter_image_model == "example/image"
    assert config.openrouter_api_key == "secret"
