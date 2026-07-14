"""Run the game loop beside the optional HTTP API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from .. import telemetry
from ..claims import ClaimSecretRegistry
from ..core.world_actor import WorldActor
from ..engine import GameLoop
from ..persistence import WorldMeta
from .app import create_app
from .auth import TokenStore, UserCredentialStore

if TYPE_CHECKING:
    from ..imagegen.service import ImageGenService
    from ..plugins.model import Plugin
    from ..worldgen import GenOptions
    from .character_chat import CharacterChatService


async def run_loop_with_api(
    loop: GameLoop,
    actor: WorldActor,
    meta: WorldMeta,
    *,
    host: str,
    port: int,
    save_path: str | Path | None = None,
    definitions_path: str | Path | None = None,
    worldgen_options: GenOptions | None = None,
    plugins: list[Plugin] | None = None,
    auth_users_path: str | Path = "data/auth-users.yml",
    token_db_path: str | Path = "data/auth-tokens.sqlite3",
    player_client_ids: str | list[str] | None = None,
    admin_client_ids: str | list[str] | None = None,
    trust_x_real_ip: bool = False,
    imagegen: ImageGenService | None = None,
    character_chat: CharacterChatService | None = None,
    claim_secrets: ClaimSecretRegistry | None = None,
    max_ticks: int | None = None,
) -> int:
    """Run uvicorn and the game loop until either one stops."""

    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "bunnyland server API requires uvicorn; install the server dependencies first"
        ) from exc

    token_store = TokenStore(token_db_path)
    app = create_app(
        actor,
        meta,
        loop=loop,
        save_path=save_path,
        definitions_path=definitions_path,
        worldgen_options=worldgen_options,
        plugins=plugins,
        token_store=token_store,
        user_credentials=UserCredentialStore(auth_users_path),
        player_client_ids=player_client_ids,
        admin_client_ids=admin_client_ids,
        trust_x_real_ip=trust_x_real_ip,
        imagegen=imagegen,
        character_chat=character_chat,
        claim_secrets=claim_secrets,
    )
    telemetry.instrument_fastapi(app)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    game_task = asyncio.create_task(loop.run(max_ticks=max_ticks))
    server_task = asyncio.create_task(server.serve())

    done, _pending = await asyncio.wait(
        {game_task, server_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if server_task in done:
        server_task.result()
        loop.stop()
        ticks = await game_task
        token_store.close()
        return ticks

    ticks = game_task.result()
    server.should_exit = True
    await server_task
    token_store.close()
    return ticks


__all__ = ["run_loop_with_api"]
