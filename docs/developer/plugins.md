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
