"""Shared application tools for LangChain and MCP adapters."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from pharm_assistant.container import get_container


def document_search_records(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Execute deterministic document retrieval and normalize tool output."""

    chunks = get_container().store.query(
        query,
        document_ids=document_ids or [],
        top_k=max(1, min(top_k, 20)),
    )
    return [
        {
            "chunk_id": chunk.id,
            "doc_id": chunk.doc_id,
            "filename": chunk.filename,
            "page": chunk.page_number,
            "section": chunk.section_title,
            "text": chunk.text,
            "score": chunk.score,
            "citation": f"[doc:{chunk.doc_id} p.{chunk.page_number}]",
        }
        for chunk in chunks
    ]


async def literature_search_records(
    query: str,
    max_results: int = 5,
) -> dict[str, Any]:
    """Execute keyless Europe PMC search and normalize tool output."""

    result = await get_container().literature.search(
        query,
        max_results=max(1, min(max_results, 10)),
    )
    return result.model_dump(mode="json")


@tool("search_medical_documents")
def search_medical_documents(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search indexed medical PDFs and return relevant page-cited excerpts."""

    return document_search_records(query, top_k, document_ids)


@tool("search_external_literature")
async def search_external_literature(
    query: str,
    max_results: int = 5,
) -> dict[str, Any]:
    """Search Europe PMC for article abstracts and stable source metadata."""

    return await literature_search_records(query, max_results)


LANGCHAIN_TOOLS = (search_medical_documents, search_external_literature)
