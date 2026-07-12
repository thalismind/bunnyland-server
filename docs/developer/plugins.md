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
