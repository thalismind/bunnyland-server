"""bunnyland command-line entrypoint.

For now this wires plugins onto a world actor and reports what was loaded. The full
``serve`` loop (Discord + LLM controllers) arrives with the integration phase.
"""

from __future__ import annotations

import argparse

from .core.world_actor import WorldActor
from .plugins import apply_plugins, bunnyland_plugins, load_modules, resolve_order, select

BUILTIN_MODULE = "bunnyland.plugins.builtin"


def build_actor(modules: list[str], enabled_ids: list[str] | None) -> tuple[WorldActor, list]:
    """Create an actor and apply builtin + requested plugins; return (actor, applied)."""
    plugins = list(bunnyland_plugins())
    plugins.extend(load_modules(modules))
    chosen = select(plugins, enabled_ids)
    actor = WorldActor()
    applied = apply_plugins(chosen, actor)
    return actor, applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunnyland")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="load plugins and start the world (WIP)")
    serve.add_argument("--module", action="append", default=[], help="import a plugin module")
    serve.add_argument("--plugin", action="append", default=None, help="enable a plugin id")

    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.print_help()
        return 0

    actor, applied = build_actor(args.module, args.plugin)
    del actor
    print("Loaded plugins:")
    for plugin in resolve_order(applied):
        print(f"  - {plugin.id} ({plugin.name}) v{plugin.version}")
    print("World actor ready. (serve loop not yet implemented)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
