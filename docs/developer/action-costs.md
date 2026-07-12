# Action lanes and effort costs

Action metadata uses two independent ideas: the **lane** determines what kind of opportunity
an action consumes, while the **effort tier** determines how many points it costs. The server
serializes the resulting numeric AP and FP values to every client.

## Choose the lane by effect

- **World** actions change shared physical, social, economic, or environmental state. They
  spend action points even when the target is not in the current room.
- **Focus** actions change private knowledge, planning, personal progression, or character
  configuration. They spend focus points.
- Use both only when an action has substantial shared execution and substantial private
  concentration. Ordinary communication is not such an action.

The lane is not a visibility rule. A private theft attempt still affects the world, while a
publicly visible skill-tree screen still contains focus actions.

## Choose the effort tier by result

| Tier | Points | Use |
| --- | ---: | --- |
| `FREE` | 0 | Communication, observation, display, cancellation, or harmless reversible configuration |
| `ROUTINE` | 1 | One ordinary atomic action affecting one actor, target, or local object |
| `EXTENDED` | 2 | Durable creation, involved work, preparation, or a multi-target effect |
| `MAJOR` | 3 | Permanent personal choice or a party/site-scale irreversible result |
| `EPIC` | 5 | A region/world-scale result or direct resolution of a complete challenge |

Normal characters hold 5 AP and regenerate 1 AP per hour. They hold 3 FP and regenerate
0.5 FP per hour. `EPIC` is therefore a world-only tier. Permanent progression such as
unlocking a perk uses all 3 FP; it cannot be repeated from one normal full focus pool.

Use the smallest tier that describes the result, not the animation or command name. Repeated
steps such as attacks and harvesting are routine. Building a durable structure is extended.
Founding a caravan or festival is major. A command that directly resolves a boss encounter
is epic.

AP and FP do not replace money, materials, stamina, magic, durability, reputation, or other
mechanic-specific resources. Those constraints remain in the handler. Points are charged
only after successful execution.

## Definition rules

Bundled actions use the named cost constants from `bunnyland.core.actions`. External plugins
use `ActionEffort` with `effort_cost`, for example:

```python
ActionDefinition(
    command_type="compose-song",
    lane=Lane.FOCUS,
    cost=effort_cost(focus=ActionEffort.EXTENDED),
)
```

The registry is the authoritative action matrix. Tests reject costs outside `0, 1, 2, 3,
5`, focus costs above 3, and a cost in the lane opposite the declared action lane. Clients
must render the registry-provided lane and numeric cost rather than maintaining their own
catalogues.
