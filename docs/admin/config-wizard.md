# Config wizard

The config wizard is the recommended way to create and maintain a Bunnyland server
configuration. It writes a YAML config for the server and deployment scripts, plus the
generated web config that the frontend container serves.

Run it from the server repo with:

```bash
uv run bunnyland config-wizard
```

For scripted or CI use, run the same command with CLI/non-interactive flags:

```bash
uv run bunnyland config-wizard --cli
uv run bunnyland config-wizard --non-interactive --config bunnyland.yml
```

## Layout

The Textual wizard is organized as a staged setup flow. The stage list on the left is
selectable, so you can move forward, jump back, or review earlier choices without walking
through every page again.

The wizard starts with the world setup and then moves through gameplay features and
integrations before ending with deployment and access details. Required fields are visible
by default. Less common operational fields are hidden until you enable advanced settings.

The bottom bar keeps the main actions visible:

- `Apply` writes the configuration once required fields are populated.
- `Close` exits without applying changes.
- `Advanced` toggles low-frequency fields.

The footer also exposes keyboard shortcuts for the same actions.

## Help and review

Each field label has a focusable `?` button. Use it from the keyboard or mouse to open a
small help dialog with short guidance and examples. Help is intentionally attached to the
field rather than embedded in the page, so the main flow stays compact.

The Review screen builds the config from the current form state and shows either a summary
or the one issue that must be fixed before saving. Review errors appear in the review body,
not in the shared page banner.

## Working with generated files

By default, the wizard reads the config path you pass with `--config` and writes back to
that path. If no file exists, it starts from safe defaults and generates fresh secrets for
the initial admin login.

The setup script consumes the generated YAML and web config through environment variables
when it launches Compose. That keeps the container runtime path simple: the YAML file is
mounted into the server container, and the rendered web config is mounted into nginx.

Use explicit output paths when you want to review generated files before applying them:

```bash
uv run bunnyland config-wizard \
  --config bunnyland.yml \
  --write-config /tmp/bunnyland.yml \
  --write-web-config /tmp/bunnyland.web.json \
  --dry-run
```

## Plugin safety

The plugin stage only imports modules that you explicitly provide with the wizard command.
Already-loaded plugin modules can be shown because their code has already run. Unloaded
modules that look relevant may be listed as suggestions, but the wizard does not import
them by itself.

Only import plugin modules that you trust.
