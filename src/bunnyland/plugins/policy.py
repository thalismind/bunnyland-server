"""Shared validation for plugin-contributed boundary scope identifiers."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

_BOUNDARY_SCOPE = re.compile(r"^[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)*$")


def validate_boundary_scope(value: str) -> str:
    """Return one canonical boundary scope or reject malformed plugin input."""

    if len(value) > 64 or _BOUNDARY_SCOPE.fullmatch(value) is None:
        raise ValueError(
            "boundary scopes must be lower-case identifiers with optional colon namespaces"
        )
    return value


BoundaryScope = Annotated[str, AfterValidator(validate_boundary_scope)]


__all__ = ["BoundaryScope", "validate_boundary_scope"]
