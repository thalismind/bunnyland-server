#!/usr/bin/env python3
"""Generate and launch a local sandbox with LLM-controlled representatives."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bunnyland.cli import main as bunnyland_main
from bunnyland.core.controllers import LLMControllerComponent
from bunnyland.core.ecs import spawn_entity
from bunnyland.core.world_actor import WorldActor
from bunnyland.persistence import WorldMeta, save_world
from bunnyland.plugins import apply_plugins, bunnyland_plugins, resolve_order, select
from bunnyland.sandbox.regions import REGIONS
from bunnyland.worldgen import CharacterSpec, GenOptions, collect_generators

DEFAULT_WORLD_PATH = Path("artifacts/sandbox-world-llm.json")


@dataclass(frozen=True)
class PreparedSandbox:
    path: Path
    controller_id: str
    representative_names: tuple[str, ...]


def representative_specs() -> tuple[CharacterSpec, ...]:
    """Return the characters deliberately placed in simpack regions."""

    return tuple(character for region in REGIONS for character in region.characters)


async def prepare_sandbox_world(
    path: Path,
    *,
    seed: str,
    provider: str,
    model: str,
    act_every_ticks: int,
    overwrite: bool = False,
) -> PreparedSandbox:
    """Generate a sandbox and assign its region representatives to one LLM controller."""

    if path.exists() and not overwrite:
        raise FileExistsError(path)

    plugins = resolve_order(select(list(bunnyland_plugins()), None))
    actor = WorldActor()
    apply_plugins(plugins, actor)
    generator = collect_generators(plugins)["bunnyland-sandbox"]
    result = await generator.generate(actor, seed, GenOptions())

    controller = spawn_entity(
        actor.world,
        [
            LLMControllerComponent(
                profile_name="default",
                provider=provider,
                model=model,
                act_every_ticks=act_every_ticks,
            )
        ],
    )
    names = []
    for spec in representative_specs():
        character_id = result.characters.get(spec.key)
        if character_id is None:
            raise RuntimeError(f"sandbox representative {spec.name!r} was not generated")
        actor.assign_controller(character_id, controller.id)
        names.append(spec.name)

    save_world(
        actor,
        path,
        meta=WorldMeta(
            seed=seed,
            generator=generator.name,
            plugins=tuple(plugin.id for plugin in plugins),
        ),
    )
    return PreparedSandbox(
        path=path,
        controller_id=str(controller.id),
        representative_names=tuple(sorted(names)),
    )


def _serve_arguments(args: argparse.Namespace) -> list[str]:
    serve = [
        "serve",
        "--load",
        str(args.world),
        "--save",
        str(args.world),
        "--llm",
        "--llm-provider",
        args.llm_provider,
        "--character-model",
        args.character_model,
        "--ticks",
        str(args.ticks),
        "--tick-seconds",
        str(args.tick_seconds),
        "--time-scale",
        str(args.time_scale),
        "--autosave-every",
        str(args.autosave_every),
        "--api-host",
        args.api_host,
        "--api-port",
        str(args.api_port),
    ]
    if args.character_chat:
        serve.append("--character-chat")
    if not args.quiet:
        serve.append("--verbose")
    return serve


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/launch-sandbox-llm",
        description=(
            "Generate a bunnyland-sandbox world, attach one LLM controller to every "
            "simpack representative, and launch the local server. New Arrivals remain "
            "suspended and claimable."
        )
    )
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD_PATH)
    parser.add_argument("--seed", default="a lively local crossroads")
    parser.add_argument(
        "--llm-provider",
        choices=("ollama", "openrouter"),
        default="openrouter",
    )
    parser.add_argument("--character-model", required=True)
    parser.add_argument("--act-every-ticks", type=int, default=6)
    parser.add_argument("--ticks", type=int, default=0)
    parser.add_argument("--tick-seconds", type=float, default=30.0)
    parser.add_argument("--time-scale", type=float, default=60.0)
    parser.add_argument("--autosave-every", type=int, default=10)
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument("--character-chat", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--force", action="store_true", help="replace an existing world file")
    output.add_argument(
        "--reuse",
        action="store_true",
        help="launch an already prepared world without regenerating it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.act_every_ticks < 1:
        parser.error("--act-every-ticks must be at least 1")

    if args.reuse:
        if not args.world.is_file():
            parser.error(f"cannot reuse missing world: {args.world}")
        print(f"Reusing prepared sandbox {args.world}.")
    else:
        if args.world.exists() and not args.force:
            parser.error(
                f"world already exists: {args.world}; use --reuse to launch it or "
                "--force to replace it"
            )
        prepared = asyncio.run(
            prepare_sandbox_world(
                args.world,
                seed=args.seed,
                provider=args.llm_provider,
                model=args.character_model,
                act_every_ticks=args.act_every_ticks,
                overwrite=args.force,
            )
        )
        names = ", ".join(prepared.representative_names)
        print(f"Prepared {prepared.path} with LLM representatives: {names}.")

    if args.prepare_only:
        return 0
    return bunnyland_main(_serve_arguments(args))


if __name__ == "__main__":
    raise SystemExit(main())
