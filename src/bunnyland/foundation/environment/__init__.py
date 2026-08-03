"""Canonical environmental state and protection contracts."""

from .mechanics import (
    MoistureComponent,
    ShelterComponent,
    ShelterProtection,
    resolve_shelter_protection,
)

__all__ = [
    "MoistureComponent",
    "ShelterComponent",
    "ShelterProtection",
    "resolve_shelter_protection",
]
