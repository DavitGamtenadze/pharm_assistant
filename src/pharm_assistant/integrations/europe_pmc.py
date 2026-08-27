"""Keyless Europe PMC literature search."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
from diskcache import Cache

from pharm_assistant.core.logging import get_logger
from pharm_assistant.models.schemas import (
    LiteratureArticle,
    LiteratureSearchResponse,
)

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class AsyncRateLimiter:
    """Apply conservative fair-use spacing to keyless external requests."""

    def __init__(self, requests_per_second: float = 1.0) -> None:
        self._interval = 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._interval - (time.monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = time.monotonic()


class EuropePmcClient:
    """Search Europe PMC metadata and abstracts without API credentials."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cache = Cache(str(cache_dir / "europe-pmc"))
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "medical-document-assistant/0.1"},
        )
        self._owns_client = client is None
        self._limiter = AsyncRateLimiter()
        self._logger = get_logger()

    async def _search_request(self, params: dict[str, Any]) -> httpx.Response:
        for attempt in range(3):
            await self._limiter.wait()
            try:
                response = await self._client.get(SEARCH_URL, params=params)
                if response.status_code != 429 and response.status_code < 500:
                    response.raise_for_status()
                    return response
                if attempt == 2:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2**attempt
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                delay = 2**attempt
            await asyncio.sleep(delay + secrets.randbelow(251) / 1000)
        raise RuntimeError("Europe PMC retry loop ended unexpectedly.")

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> LiteratureSearchResponse:
        normalized = " ".join(query.split())
        max_results = max(1, min(max_results, 10))
        cache_key = (
            "search:"
            + hashlib.sha256(f"{normalized.casefold()}:{max_results}".encode()).hexdigest()
        )
        cached = self._cache.get(cache_key)
        if isinstance(cached, list):
            return LiteratureSearchResponse(
                articles=[LiteratureArticle.model_validate(item) for item in cached],
                cached=True,
            )

        started = time.perf_counter()
        try:
            response = await self._search_request(
                {
                    "query": normalized,
                    "resultType": "core",
                    "pageSize": max_results,
                    "format": "json",
                    "synonym": "true",
                }
            )
            results = response.json().get("resultList", {}).get("result", [])
            articles = [article for item in results if (article := _parse_result(item)) is not None]
            self._cache.set(
                cache_key,
                [article.model_dump(mode="json") for article in articles],
                expire=86_400,
            )
            self._logger.info(
                "literature_search_complete",
                provider="europe_pmc",
                result_count=len(articles),
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
            return LiteratureSearchResponse(articles=articles)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            self._logger.warning(
                "literature_search_failed",
                provider="europe_pmc",
                error_type=type(exc).__name__,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
            return LiteratureSearchResponse(
                articles=[],
                error=(
                    "External literature is temporarily unavailable; document search continued."
                ),
            )

    async def close(self) -> None:
        self._cache.close()
        if self._owns_client:
            await self._client.aclose()


def _parse_result(item: dict[str, Any]) -> LiteratureArticle | None:
    source = str(item.get("source") or "MED").upper()
    identifier = str(item.get("id") or item.get("pmid") or item.get("pmcid") or "")
    title = " ".join(str(item.get("title") or "").split())
    if not identifier or not title:
        return None

    year_value = str(item.get("pubYear") or "")
    year = int(year_value) if year_value.isdigit() else None
    return LiteratureArticle(
        id=identifier,
        source=source,
        pmid=str(item["pmid"]) if item.get("pmid") else None,
        title=title,
        journal=str(item["journalTitle"]) if item.get("journalTitle") else None,
        year=year,
        abstract=" ".join(str(item.get("abstractText") or "").split()),
        doi=str(item["doi"]) if item.get("doi") else None,
        url=f"https://europepmc.org/article/{source}/{identifier}",
    )
