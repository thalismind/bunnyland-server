"""Shared Textual picker for local terminal world generation."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..terminal_generators import group_generators

if TYPE_CHECKING:
    from ..worldgen import WorldGenerator


DEFAULT_LOCAL_GENERATOR = "apartment-demo"
DEFAULT_LOCAL_SEED = "a quiet marsh"
PRESET_SEEDS = (
    "a quiet marsh",
    "apple crossing dawn",
    "bell green market day",
    "clover city evening",
    "lanterns after rain",
    "storm over the old footbridge",
)


@dataclass(frozen=True)
class GeneratorSelection:
    """Selected local generation inputs."""

    generator: str
    seed: str


def random_preset_seed() -> str:
    return secrets.choice(PRESET_SEEDS)


class WorldGeneratorSelector(ModalScreen[GeneratorSelection | None]):
    """Pick a local world generator and seed before starting an offline client."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    WorldGeneratorSelector { align: center middle; }
    #generator-picker {
        width: 76; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    #generator-title { text-style: bold; }
    #generator-hint { color: $text-muted; height: auto; padding-bottom: 1; }
    #generator-list { height: 18; margin-bottom: 1; }
    #generator-description { height: auto; min-height: 2; color: $text-muted; }
    #seed-row { height: 3; }
    #seed-input { width: 1fr; }
    #seed-random { width: 14; min-width: 14; }
    #generator-error { color: $error; height: 1; }
    #generator-buttons { height: auto; padding-top: 1; }
    #generator-start { margin-right: 1; }
    """

    def __init__(
        self,
        generators: list[WorldGenerator],
        *,
        initial_generator: str = DEFAULT_LOCAL_GENERATOR,
        initial_seed: str = DEFAULT_LOCAL_SEED,
    ) -> None:
        super().__init__()
        self.generators = sorted(generators, key=lambda generator: generator.name)
        self.initial_generator = initial_generator
        self.initial_seed = initial_seed
        self.selected_generator = self._initial_generator()

    def compose(self) -> ComposeResult:
        with Vertical(id="generator-picker"):
            yield Label("Choose a world", id="generator-title")
            yield Static(
                "Select a local generator, then set a seed when the seed field is enabled.",
                id="generator-hint",
            )
            yield OptionList(id="generator-list")
            yield Static("", id="generator-description")
            with Horizontal(id="seed-row"):
                yield Input(self.initial_seed, id="seed-input", placeholder="seed")
                yield Button("Random Seed", id="seed-random")
            yield Static("", id="generator-error")
            with Horizontal(id="generator-buttons"):
                yield Button("Select", id="generator-start", variant="primary")
                yield Button("Cancel", id="generator-cancel")

    def on_mount(self) -> None:
        options = self.query_one("#generator-list", OptionList)
        for group, generators in group_generators(self.generators).items():
            header = Text(f" {group.replace('-', ' ').upper()} ", style="bold reverse")
            options.add_option(Option(header, disabled=True))
            for generator in generators:
                label = Text("  ")
                label.append(generator.name, style="bold")
                option_id = f"generator:{generator.name}"
                options.add_option(Option(label, id=option_id))
        options.highlighted = options.get_option_index(f"generator:{self.selected_generator.name}")
        self._sync_seed_state()
        options.focus()

    def _initial_generator(self) -> WorldGenerator:
        for generator in self.generators:
            if generator.name == self.initial_generator:
                return generator
        if not self.generators:
            raise ValueError("world generator selector needs at least one generator")
        return self.generators[0]

    def _generator_by_name(self, name: str) -> WorldGenerator | None:
        return next((generator for generator in self.generators if generator.name == name), None)

    def _sync_seed_state(self) -> None:
        description = self.selected_generator.description or "No description."
        self.query_one("#generator-description", Static).update(description)
        seed_input = self.query_one("#seed-input", Input)
        random = self.query_one("#seed-random", Button)
        seed_input.disabled = not self.selected_generator.uses_seed
        random.disabled = not self.selected_generator.uses_seed

    @on(OptionList.OptionSelected, "#generator-list")
    def _generator_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id or "")
        if not option_id.startswith("generator:"):
            return
        generator = self._generator_by_name(option_id.removeprefix("generator:"))
        if generator is None:
            return
        self.selected_generator = generator
        self._sync_seed_state()

    @on(Button.Pressed, "#seed-random")
    def _random_seed_pressed(self, _event: Button.Pressed) -> None:
        self.query_one("#seed-input", Input).value = random_preset_seed()

    @on(Input.Submitted, "#seed-input")
    def _seed_submitted(self, _event: Input.Submitted) -> None:
        self._start()

    @on(Button.Pressed, "#generator-start")
    def _start_pressed(self, _event: Button.Pressed) -> None:
        self._start()

    @on(Button.Pressed, "#generator-cancel")
    def _cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _start(self) -> None:
        seed = self.query_one("#seed-input", Input).value.strip()
        if self.selected_generator.uses_seed and not seed:
            self.query_one("#generator-error", Static).update("Seed is required.")
            return
        self.dismiss(
            GeneratorSelection(
                generator=self.selected_generator.name,
                seed=seed or self.initial_seed or DEFAULT_LOCAL_SEED,
            )
        )
