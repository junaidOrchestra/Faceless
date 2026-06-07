"""Pluggable stock media sources.

Importing this package registers built-in sources via the ``@register_source``
decorator side effects in each module.
"""

from .base import Candidate, StockSource
from .registry import get_source, list_sources, register_source

# Side-effect imports register sources with the global registry.
from . import pexels_photo as _pexels_photo  # noqa: F401
from . import pexels_video as _pexels_video  # noqa: F401
from . import pixabay_photo as _pixabay_photo  # noqa: F401
from . import pixabay_video as _pixabay_video  # noqa: F401
from . import stub as _stub  # noqa: F401
from . import wikimedia as _wikimedia  # noqa: F401

__all__ = [
    "Candidate",
    "StockSource",
    "get_source",
    "list_sources",
    "register_source",
]
