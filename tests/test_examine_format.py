"""Tests for the shared examine-view formatting helpers."""

from __future__ import annotations

from bunnyland.examine_format import examine_detail_lines, examine_header


def test_examine_header_variants():
    assert examine_header({"name": "Juniper", "kind": "character", "is_self": True}) == (
        "Juniper (character) (you)"
    )
    assert examine_header({"name": "bun", "kind": "food"}, icon="🍎") == "🍎 bun (food)"
    # Falls back to the id and a default kind when name/kind are missing.
    assert examine_header({"id": "entity:7"}) == "entity:7 (other)"


def test_examine_detail_lines_public_facets():
    view = {
        "is_self": False,
        "details": {
            "description": {"short": "A crusty roll.", "appearance": "golden", "long": ""},
            "condition": ["asleep"],
            "food": {"nutrition": 5.0, "satiety": 10.5, "raw": True, "spoiled": True},
            "drinkable": {"hydration": 3.0, "purity": 0.5},
            "door": {"open": False},
            "container": {"open": False, "locked": True},
            "light": {"enabled": True, "level": 1.0},
            "portable": {"can_pick_up": True},
        },
    }
    assert examine_detail_lines(view) == [
        "A crusty roll.",
        "golden",
        "Condition: asleep",
        "Food — nutrition 5, satiety 10.5 (raw, spoiled)",
        "Drink — hydration 3 (impure)",
        "Door — closed",
        "Container — closed, locked",
        "Light — on (level 1)",
        "Can be carried.",
    ]


def test_examine_detail_lines_open_states_and_pure_drink():
    view = {
        "details": {
            "drinkable": {"hydration": 2.0},
            "door": {"open": True},
            "container": {"open": True},
            "light": {"enabled": False, "level": 0.0},
        },
    }
    assert examine_detail_lines(view) == [
        "Drink — hydration 2",
        "Door — open",
        "Container — open",
        "Light — off (level 0)",
    ]


def test_examine_detail_lines_self_adds_mood_status_and_points():
    view = {
        "is_self": True,
        "details": {"affect": {"labels": ["content", "curious"]}},
        "status": ["You are getting hungry.", "  ", ""],
        "points": {"action": 5.0, "action_max": 5.0, "focus": 1.5, "focus_max": 3.0},
    }
    assert examine_detail_lines(view) == [
        "Mood: content, curious",
        "You are getting hungry.",
        "AP 5/5 · FP 1.5/3",
    ]


def test_examine_detail_lines_points_skipped_when_not_self():
    view = {
        "is_self": False,
        "points": {"action": 5.0, "action_max": 5.0, "focus": 1.0, "focus_max": 3.0},
    }
    assert examine_detail_lines(view) == []


def test_examine_detail_lines_empty_view():
    assert examine_detail_lines({}) == []
