"""Global registry of :class:`StockSource` implementations.

New sources are added by decorating a class with :func:`register_source` in its
module; importing that module (from ``sources/__init__.py``) performs registration.
"""

from __future__ import annotations

from typing import TypeVar

from .base import StockSource

T = TypeVar("T", bound=type[StockSource])

_REGISTRY: dict[str, type[StockSource]] = {}


def register_source(cls: T) -> T:
    """Class decorator that registers a stock source under ``cls.name``."""

    if not getattr(cls, "name", None):
        raise ValueError(f"StockSource {cls.__name__} must define 'name'.")
    _REGISTRY[cls.name] = cls
    return cls


def get_source(name: str) -> StockSource:
    """Instantiate a registered source by name."""

    try:
        return _REGISTRY[name]()
    except KeyError as exc:
        raise KeyError(f"Unknown source: {name}") from exc


def list_sources() -> list[str]:
    """Return registered source names (stable sorted order)."""

    return sorted(_REGISTRY.keys())
