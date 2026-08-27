"""Persistent dense retrieval with Chroma."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from pharm_assistant.models.schemas import DocumentSummary
from pharm_assistant.services.chunking import DocumentChunk
from pharm_assistant.services.embeddings import Embedder

_TOKEN = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "what",
        "which",
        "when",
        "where",
        "does",
        "how",
        "are",
        "was",
        "were",
        "should",
        "must",
        "into",
        "about",
        "according",
        "document",
        "report",
        "guideline",
    }
)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    id: str
    doc_id: str
    filename: str
    page_number: int
    section_title: str
    text: str
    score: float


class ChromaDocumentStore:
    """Store document chunks and their vectors in a local Chroma collection."""

    def __init__(self, path: Path | None, embedder: Embedder) -> None:
        self._embedder = embedder
        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        self._client = (
            chromadb.PersistentClient(path=str(path), settings=chroma_settings)
            if path is not None
            else chromadb.EphemeralClient(settings=chroma_settings)
        )
        self._collection = self._client.get_or_create_collection(
            name="medical_documents",
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_document(
        self,
        summary: DocumentSummary,
        chunks: list[DocumentChunk],
    ) -> None:
        """Replace an existing document by deleting its chunks, then upserting."""

        self.delete_document(summary.id)
        created_at = summary.created_at.isoformat()
        for start in range(0, len(chunks), 100):
            batch = chunks[start : start + 100]
            self._collection.upsert(
                ids=[chunk.id for chunk in batch],
                documents=[chunk.text for chunk in batch],
                embeddings=self._embedder.embed([chunk.text for chunk in batch]),
                metadatas=[
                    {
                        "doc_id": chunk.doc_id,
                        "filename": chunk.filename,
                        "page_number": chunk.page_number,
                        "section_title": chunk.section_title,
                        "page_count": summary.page_count,
                        "chunk_count": summary.chunk_count,
                        "size_bytes": summary.size_bytes,
                        "created_at": created_at,
                    }
                    for chunk in batch
                ],
            )

    def ready(self) -> bool:
        try:
            self._collection.count()
        except Exception:
            return False
        return True

    def delete_document(self, doc_id: str) -> None:
        self._collection.delete(where={"doc_id": doc_id})

    def list_documents(self) -> list[DocumentSummary]:
        if self._collection.count() == 0:
            return []
        result = self._collection.get(include=["metadatas"])
        by_id: dict[str, DocumentSummary] = {}
        for metadata in result.get("metadatas") or []:
            if not metadata:
                continue
            doc_id = str(metadata["doc_id"])
            if doc_id in by_id:
                continue
            by_id[doc_id] = DocumentSummary(
                id=doc_id,
                filename=str(metadata["filename"]),
                page_count=int(metadata["page_count"]),
                chunk_count=int(metadata["chunk_count"]),
                size_bytes=int(metadata["size_bytes"]),
                created_at=datetime.fromisoformat(str(metadata["created_at"])),
            )
        return sorted(by_id.values(), key=lambda item: item.created_at, reverse=True)

    def query(
        self,
        query: str,
        *,
        document_ids: list[str],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if self._collection.count() == 0:
            return []

        where: dict[str, Any] | None = None
        if len(document_ids) == 1:
            where = {"doc_id": document_ids[0]}
        elif document_ids:
            where = {"doc_id": {"$in": document_ids}}

        candidate_k = min(max(top_k * 3, top_k), self._collection.count())
        result = self._collection.query(
            query_embeddings=self._embedder.embed([query]),
            n_results=candidate_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for chunk_id, text, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=False
        ):
            if text is None or metadata is None:
                continue
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            chunks.append(
                RetrievedChunk(
                    id=str(chunk_id),
                    doc_id=str(metadata["doc_id"]),
                    filename=str(metadata["filename"]),
                    page_number=int(metadata["page_number"]),
                    section_title=str(metadata["section_title"]),
                    text=str(text),
                    score=score,
                )
            )
        return rerank_chunks(query, chunks, top_k)


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(value.casefold()) if token not in _STOPWORDS}


def rerank_chunks(query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
    """Blend cosine rank with lexical and section-title overlap."""

    query_tokens = _tokens(query)
    if not chunks or not query_tokens:
        return chunks[:top_k]

    ranked: list[tuple[float, int, RetrievedChunk]] = []
    for index, chunk in enumerate(chunks):
        text_overlap = len(query_tokens & _tokens(chunk.text)) / len(query_tokens)
        title_overlap = len(query_tokens & _tokens(chunk.section_title)) / len(query_tokens)
        combined = chunk.score + (0.28 * text_overlap) + (0.18 * title_overlap)
        ranked.append((combined, index, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [chunk for _, _, chunk in ranked[:top_k]]
