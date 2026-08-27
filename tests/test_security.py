from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from pharm_assistant.core.config import Settings
from pharm_assistant.core.rate_limit import RateLimiter
from pharm_assistant.main import app


def test_production_requires_an_api_key(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="APP_API_KEY"):
        Settings(data_dir=tmp_path, env="production", api_key="")


def test_production_rejects_wildcard_cors(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS"):
        Settings(
            data_dir=tmp_path,
            env="production",
            api_key="secret",
            allowed_origins="*",
        )


def test_rate_limiter_blocks_bursts() -> None:
    limiter = RateLimiter(1, window_seconds=60)
    limiter.check("client-a")
    with pytest.raises(HTTPException, match="Too many requests"):
        limiter.check("client-a")
    limiter.check("client-b")


@pytest.mark.asyncio
async def test_health_includes_readiness_and_security_headers() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    payload = response.json()
    assert response.status_code == 200
    assert "store_ready" in payload
    assert "document_count" in payload
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
