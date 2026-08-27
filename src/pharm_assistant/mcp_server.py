"""MCP tools that expose the same retrieval boundaries as the HTTP API."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from pharm_assistant.tooling import (
    document_search_records,
    literature_search_records,
)

mcp = MCPServer(
    "medical-document-assistant",
    description="Page-cited medical document retrieval and keyless literature search.",
)


@mcp.tool()
def search_documents(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search indexed medical documents and return page-citable chunks."""

    return document_search_records(query, top_k, document_ids)


@mcp.tool()
async def search_literature(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search Europe PMC and return structured, citable article metadata."""

    return await literature_search_records(query, max_results)


def run() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
