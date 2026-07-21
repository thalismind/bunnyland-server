"""bunnyland: an async social sandbox on the Relics ECS."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bunnyland")
except PackageNotFoundError:  # source tree imported without installing the project
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
