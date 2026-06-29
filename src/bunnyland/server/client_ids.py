"""Role-scoped client_id allowlist helpers."""

from __future__ import annotations

import os
from collections.abc import Sequence

PLAYER_CLIENT_IDS_ENV = "BUNNYLAND_PLAYER_CLIENT_IDS"
ADMIN_CLIENT_IDS_ENV = "BUNNYLAND_ADMIN_CLIENT_IDS"
CLIENT_ID_HEADER = "X-Bunnyland-Client-Id"


def parse_client_id_allowlist(value: str | Sequence[str] | None) -> frozenset[str]:
    if value is None:
        return frozenset()
    values = [value] if isinstance(value, str) else list(value)
    allowed: set[str] = set()
    for item in values:
        for client_id in str(item).replace("\n", ",").split(","):
            normalized = client_id.strip()
            if normalized:
                allowed.add(normalized)
    return frozenset(allowed)


def configured_client_id_allowlist(
    configured: str | Sequence[str] | None, env_name: str
) -> frozenset[str]:
    if configured is not None:
        return parse_client_id_allowlist(configured)
    return parse_client_id_allowlist(os.environ.get(env_name))


def require_allowed_client_id(
    client_id: str | None, allowed: frozenset[str], role: str
) -> str | None:
    if not allowed:
        return client_id.strip() if isinstance(client_id, str) else None
    normalized = client_id.strip() if isinstance(client_id, str) else ""
    if not normalized:
        raise PermissionError(f"{role} client_id is required")
    if normalized not in allowed:
        raise PermissionError(f"{role} client_id is not allowed")
    return normalized


__all__ = [
    "ADMIN_CLIENT_IDS_ENV",
    "CLIENT_ID_HEADER",
    "PLAYER_CLIENT_IDS_ENV",
    "configured_client_id_allowlist",
    "parse_client_id_allowlist",
    "require_allowed_client_id",
]
