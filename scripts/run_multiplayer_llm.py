#!/usr/bin/env python3
"""Run the configurable live multiplayer LLM playtest harness."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from bunnyland.playtest import (
    MultiplayerHarness,
    NdjsonAdminTraceWriter,
    load_multiplayer_config,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run independent LLM players concurrently against one Bunnyland server."
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--trace-output",
        type=Path,
        help="Sensitive live admin NDJSON (default: OUTPUT with .trace.ndjson suffix)",
    )
    return parser


async def _run(config_path: Path, output: Path, trace_output: Path | None = None) -> int:
    config = load_multiplayer_config(config_path)
    trace_path = trace_output or output.with_suffix(".trace.ndjson")
    trace_writer = NdjsonAdminTraceWriter(trace_path)
    print(f"Sensitive admin trace: {trace_path} (monitor with: tail -f {trace_path})")
    result = await MultiplayerHarness(config, admin_trace_sink=trace_writer).run()
    result.write_json(output)
    completed = result.completed_players
    total = len(result.players)
    print(f"Multiplayer run complete: {completed}/{total} players completed; {output}")
    for player in result.players:
        detail = f" ({player.error})" if player.error else ""
        print(
            f"  {player.name}: {player.status}, {len(player.turns)} turn(s), "
            f"{player.elapsed_seconds:.1f}s{detail}"
        )
    return 0 if all(player.status != "failed" for player in result.players) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args.config, args.output, args.trace_output))


if __name__ == "__main__":
    raise SystemExit(main())
