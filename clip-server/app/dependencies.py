"""FastAPI dependency injection wiring."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import get_session
from .embedding.base import Embedder


def get_embedder(request: Request) -> Embedder:
    """Return the CLIP embedder loaded at application startup."""

    embedder: Embedder | None = getattr(request.app.state, "embedder", None)
    if embedder is None:
        raise RuntimeError("Embedder not initialized.")
    return embedder


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
