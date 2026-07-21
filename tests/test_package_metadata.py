from __future__ import annotations

import importlib
import importlib.metadata
from importlib.metadata import PackageNotFoundError, metadata, version
from importlib.resources import files

import bunnyland


def test_runtime_version_comes_from_distribution_metadata() -> None:
    assert bunnyland.__version__ == version("bunnyland") == "1.0.0rc1"


def test_runtime_version_has_source_tree_fallback(monkeypatch) -> None:
    def missing_version(_distribution_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing_version)
    reloaded = importlib.reload(bunnyland)
    assert reloaded.__version__ == "0.0.0+unknown"

    monkeypatch.undo()
    importlib.reload(bunnyland)


def test_v1_distribution_metadata_declares_supported_runtime() -> None:
    package = metadata("bunnyland")

    assert package["License-Expression"] == "AGPL-3.0-or-later"
    assert set(package["Requires-Python"].split(",")) == {">=3.12", "<3.15"}
    assert {
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    } <= set(package.get_all("Classifier", []))


def test_distribution_declares_pep561_typing_support() -> None:
    assert files("bunnyland").joinpath("py.typed").is_file()
