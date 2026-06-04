"""Deterministic stub source for tests (no network, no API key)."""

from __future__ import annotations

from typing import Any

from .base import Candidate, StockSource
from .registry import register_source


@register_source
class StubSource(StockSource):
    """Returns synthetic candidates so smoke tests never hit the network."""

    name = "stub"
    platform = "stub"
    requires_key = False
    media_kinds = ("photo", "video")

    async def search(
        self,
        query: str,
        n: int,
        credentials: dict[str, str | None],
        options: dict[str, Any],
        *,
        http_client: Any,
    ) -> list[Candidate]:
        del credentials, options, http_client
        results: list[Candidate] = []
        for i in range(min(n, 3)):
            results.append(
                Candidate(
                    platform="stub",
                    external_id=f"{query.replace(' ', '-')}-{i}",
                    kind="photo",
                    # stub:// previews are synthesized in-process (no network in tests).
                    preview_url=f"stub://preview/{query}/{i}",
                    media_url=f"https://example.com/media/{query}/{i}",
                    attribution_name="Stub Media",
                    attribution_url="https://example.com/stub",
                    license="CC0",
                    duration=None,
                    raw={"query": query, "index": i},
                )
            )
        return results
