#!/usr/bin/env python3
"""Prepare a private ten-player world and short-lived local credentials."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from bunnyland.playtest.fixture import (
    DEFAULT_FIXTURE_PLAYERS,
    DEFAULT_TOKEN_LIFETIME_SECONDS,
    prepare_multiplayer_fixture,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--players", type=int, default=DEFAULT_FIXTURE_PLAYERS)
    parser.add_argument(
        "--token-lifetime-seconds",
        type=int,
        default=DEFAULT_TOKEN_LIFETIME_SECONDS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixture = asyncio.run(
        prepare_multiplayer_fixture(
            args.output,
            player_count=args.players,
            token_lifetime_seconds=args.token_lifetime_seconds,
        )
    )
    print(f"Prepared {len(fixture.character_names)} players in {fixture.output}.")
    print(f"Source credentials from {fixture.environment} before running the harness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
