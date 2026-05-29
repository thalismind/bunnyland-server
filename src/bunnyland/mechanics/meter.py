"""Shared need-meter primitive (spec 11.11).

Needs that rise and fall (hunger, thirst, fatigue, ...) reuse this value object but live
in their own domain components. Higher ``value`` means a more pressing need. ``band``
maps the value to a coarse semantic level for prompts and projections.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Meter:
    value: float = 0.0
    minimum: float = 0.0
    maximum: float = 100.0
    warning_at: float = 40.0
    urgent_at: float = 70.0
    crisis_at: float = 90.0


def with_value(meter: Meter, value: float) -> Meter:
    """Return a copy of ``meter`` with ``value`` clamped to [minimum, maximum]."""
    clamped = max(meter.minimum, min(meter.maximum, value))
    return replace(meter, value=clamped)


def changed(meter: Meter, delta: float) -> Meter:
    return with_value(meter, meter.value + delta)


def band(meter: Meter) -> str:
    """Coarse severity band: calm < warning < urgent < crisis."""
    if meter.value >= meter.crisis_at:
        return "crisis"
    if meter.value >= meter.urgent_at:
        return "urgent"
    if meter.value >= meter.warning_at:
        return "warning"
    return "calm"


__all__ = ["Meter", "band", "changed", "with_value"]
