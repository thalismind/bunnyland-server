# Plugins

Python plugins expose `bunnyland_plugins()` and are loaded with `--import`. The MOTD claim
example in `examples/plugins/motd_claim.py` shows two extension points:

- a runtime event listener subscribed to `CharacterClaimedEvent`
- an ECS system contributed through `EcsContribution.systems`

Run it with:

```bash
uv run bunnyland serve \
  --import examples.plugins.motd_claim \
  --plugin motd_claim \
  --discord
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
