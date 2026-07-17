# Plugins

Python plugins are installed packages discovered through the canonical
`bunnyland.plugins` entry-point group. There are no runtime module-import aliases: install
the plugin wheel into the server environment, then use `--plugin` only when selecting an
explicit subset of discovered plugin ids.

```toml
[project.entry-points."bunnyland.plugins"]
"example.motd" = "example_motd.plugin:plugin"
```

The target may be a `Plugin`, a callable returning one, or a callable returning a sequence
of plugins. Plugin ids are globally stable namespaced identifiers. Discovery validates the
returned objects before dependency ordering or world loading begins.

The MOTD claim example shows two extension points:

- a runtime event listener subscribed to `CharacterClaimedEvent`
- an ECS system contributed through `EcsContribution.systems`

After packaging the example with the entry point above, install its wheel and run it with:

```bash
uv pip install --python .venv/bin/python dist/example_motd-*.whl
uv run bunnyland serve --plugin example.motd --discord
```

The claim event is controller-agnostic. The example checks whether the event's
`controller_id` points to an entity with `DiscordControllerComponent`; it does not store
Discord-specific fields on the event. Each greeting is a separate MOTD entity linked from
the character by a `HasMotdMessage` edge, because a character can receive many greetings
over time.

## Plugin config

Plugins that need YAML settings should declare a `ConfigContribution` instead of reusing
policy fields. The config block lives under `plugins.config.<plugin-id>` in
`bunnyland.yml`, is validated before plugins are applied, and is passed to runtime
factories through `PluginRuntimeContext`.

```python
from pydantic import BaseModel

from bunnyland.plugins import ConfigContribution, Plugin, RuntimeContribution


class GreetingConfig(BaseModel):
    message: str


def install_greeting(actor, context):
    config = context.config_for("example.greeting")
    ...


plugin = Plugin(
    id="example.greeting",
    name="Greeting",
    config=ConfigContribution(model=GreetingConfig),
    runtime=RuntimeContribution(service_factories=(install_greeting,)),
)
```

## Generation capabilities

Generation capabilities are also stable namespaced identifiers. Proposals, child requests,
prompt examples, and enrichers must use the exact registered capability; aliases are not
expanded at runtime.

```python
plugin = Plugin(
    id="example.forest",
    name="Forest",
    content=ContentContribution(
        generation_capabilities=("example.forest/ancient-grove",),
    ),
)
```

An unmet or misspelled capability stays unmet, which makes generation failures explicit and
keeps separately installed addons from accidentally claiming each other's content.

## Prompt filters

Plugins can contribute asynchronous post-render text filters through
`ContentContribution.prompt_filters`. A filter definition has a stable ID, a plugin-owned
typed component, and one async handler. Filter configuration is persisted on ordinary ECS
entities; a character is linked to each active filter entity by `PromptFilterBinding`.
The binding's `order` controls sequential execution, and separate entities allow several
instances of the same filter type.

```python
from pydantic.dataclasses import dataclass
from relics import Component

from bunnyland.plugins import ContentContribution, EcsContribution, Plugin
from bunnyland.prompts import PromptFilterDefinition


@dataclass(frozen=True)
class EchoFilterComponent(Component):
    repeats: int = 1


async def echo_filter(text, context, component):
    return text + (" echo" * component.repeats)


plugin = Plugin(
    id="example.echo",
    name="Echo",
    ecs=EcsContribution(components=(EchoFilterComponent,)),
    content=ContentContribution(
        prompt_filters=(
            PromptFilterDefinition(
                id="example.echo.repeat",
                component_type=EchoFilterComponent,
                handler=echo_filter,
            ),
        ),
    ),
)
```

Handlers receive the preceding text plus read-only access to the character, filter entity,
world, structured prompt context, epoch, and configured memory/LLM services. Failures are
logged and leave the preceding text unchanged. Because the stack is ordered, an obscuring
filter should follow any prose-rewriting filter that must not reconstruct hidden details.
The built-in storyteller component also accepts a short persisted `instruction` string for
voice and style, while its factual and operational preservation rules remain mandatory.

## Image generators

Plugins can contribute a named image generator factory through
`ContentContribution.image_generators`. The factory receives the global `ImageGenConfig` and
the contributing plugin's already validated YAML config. Its generator resolves a profile for
the requested purpose and implements one uniformly async `generate` method returning PNG bytes.
Provider workflow graphs and credentials stay inside the implementation; API requests never
carry them.

```python
from bunnyland.imagegen import ImageGeneratorProfile, ImagePurpose
from bunnyland.plugins import ContentContribution, Plugin


class AcmeGenerator:
    name = "acme"

    def resolve_profile(self, purpose, profile_name=""):
        return ImageGeneratorProfile(name=profile_name or purpose.value, purpose=purpose)

    async def generate(self, request):
        return await acme_png(request.prompt, request.seed, request.width, request.height)


class AcmeFactory:
    name = "acme"

    def __call__(self, image_config, plugin_config):
        return AcmeGenerator()


plugin = Plugin(
    id="example.acme-images",
    name="Acme Images",
    content=ContentContribution(image_generators=(AcmeFactory(),)),
)
```

Generator names are global. Duplicate registrations, configured unknown names, and unsupported
profiles fail during startup or the job respectively; providers are never used as implicit
fallbacks for one another.
