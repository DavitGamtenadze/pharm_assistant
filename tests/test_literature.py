from pathlib import Path

import httpx
import pytest

from pharm_assistant.integrations.europe_pmc import EuropePmcClient


class NoWaitLimiter:
    async def wait(self) -> None:
        return None


@pytest.mark.asyncio
async def test_europe_pmc_retries_and_returns_citable_metadata(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "id": "12345678",
                            "source": "MED",
                            "pmid": "12345678",
                            "title": "A controlled medical study",
                            "journalTitle": "Example Journal",
                            "pubYear": "2026",
                            "abstractText": "The primary endpoint improved.",
                            "doi": "10.1000/example",
                        }
                    ]
                }
            },
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = EuropePmcClient(cache_dir=tmp_path, client=http_client)
    client._limiter = NoWaitLimiter()  # type: ignore[assignment]
    try:
        result = await client.search("controlled medical study", max_results=3)
    finally:
        await client.close()
        await http_client.aclose()

    assert result.error is None
    assert calls == 2
    assert result.articles[0].pmid == "12345678"
    assert str(result.articles[0].url) == "https://europepmc.org/article/MED/12345678"
