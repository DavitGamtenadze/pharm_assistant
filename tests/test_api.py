from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from pharm_assistant.container import get_container
from pharm_assistant.core.config import Settings, get_settings
from pharm_assistant.main import app


class FakeDocuments:
    def list_documents(self) -> list[object]:
        return []


@pytest.mark.asyncio
async def test_document_routes_enforce_configured_api_key(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, api_key="test-secret", env="test")
    settings.ensure_directories()
    services = SimpleNamespace(
        documents=FakeDocuments(),
        generator=SimpleNamespace(is_configured=True),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_container] = lambda: services
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            unauthorized = await client.get("/api/v1/documents")
            authorized = await client.get(
                "/api/v1/documents",
                headers={"X-API-Key": "test-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json() == {"documents": []}


@pytest.mark.asyncio
async def test_question_requires_a_selected_source() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/questions",
            json={
                "question": "What does the document report?",
                "document_ids": [],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Select at least one document or enable external literature."
    )


class DummyEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


@pytest.mark.asyncio
async def test_document_file_is_served_inline(tmp_path: Path) -> None:
    from pharm_assistant.services.documents import DocumentService
    from pharm_assistant.services.vector_store import ChromaDocumentStore

    settings = Settings(data_dir=tmp_path, env="test")
    settings.ensure_directories()
    store = ChromaDocumentStore(None, DummyEmbedder())
    documents = DocumentService(settings, store)
    summary = documents.ingest("sample.pdf", _tiny_pdf())
    services = SimpleNamespace(
        documents=documents,
        generator=SimpleNamespace(is_configured=True),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_container] = lambda: services
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get("/api/v1/documents/aaaaaaaaaaaaaaaaaaaaaaaa/file")
            found = await client.get(f"/api/v1/documents/{summary.id}/file")
            missing_page = await client.get(
                f"/api/v1/documents/{summary.id}/pages/99"
            )
            page = await client.get(f"/api/v1/documents/{summary.id}/pages/1")
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 404
    assert found.status_code == 200
    assert found.headers["content-type"].startswith("application/pdf")
    assert found.content.startswith(b"%PDF-")
    assert missing_page.status_code == 404
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("image/png")
    assert page.content.startswith(b"\x89PNG")


def _tiny_pdf() -> bytes:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "High-alert medicines require an independent double check.")
    value = document.tobytes()
    document.close()
    return value
