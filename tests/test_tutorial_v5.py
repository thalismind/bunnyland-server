from pathlib import Path

import pytest

from benchmarks.tutorial_v5 import (
    DEFAULT_MATRIX,
    _validate_artifacts,
    command,
    load_cells,
)

EXPECTED_PROVIDERS = {"ollama-cloud", "ollama-local", "openrouter"}


def test_v5_matrix_freezes_historical_panel_and_trace_retention() -> None:
    config, cells = load_cells(DEFAULT_MATRIX)

    assert len(cells) == 40
    assert len({cell.model for cell in cells}) == 40
    assert {cell.provider for cell in cells} == EXPECTED_PROVIDERS
    assert sum(cell.enabled for cell in cells) == 39
    disabled = [cell for cell in cells if not cell.enabled]
    assert [cell.model for cell in disabled] == ["anthropic/claude-opus-5"]
    assert config["server_commit"] == "ce34bbe03d32c27cfc324aab9673e19d1445f8fe"
    assert (
        config["model_panel_sha256"]
        == "ecfcc74800d564421c2fd8c49b0d54945350316d687188e24f49f7b62157a549"
    )


def test_every_v5_command_is_single_model_and_retains_thinking() -> None:
    config, cells = load_cells(DEFAULT_MATRIX)

    for cell in cells:
        args = command(config, cell, Path("artifacts/v5"))
        assert args.count("--model") == 1
        assert args[args.index("--model") + 1] == cell.model
        assert "--log-thinking" in args
        assert args.count("--tutorial") == 3
        assert "--temperature" not in args
        assert "--max-output-tokens" not in args


def test_v5_matrix_rejects_disabled_trace_retention(tmp_path: Path) -> None:
    text = DEFAULT_MATRIX.read_text(encoding="utf-8").replace(
        '"log_thinking": true',
        '"log_thinking": false',
        1,
    )
    path = tmp_path / "matrix.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="must retain thinking traces"):
        load_cells(path)


def test_v5_artifact_validation_rejects_missing_cells(tmp_path: Path) -> None:
    config, cells = load_cells(DEFAULT_MATRIX)

    errors = _validate_artifacts(config, cells, tmp_path)

    assert len(errors) == 39
    assert all(error.endswith("missing manifest") for error in errors)
