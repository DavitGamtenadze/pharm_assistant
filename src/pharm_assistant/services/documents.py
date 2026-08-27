"""Document lifecycle orchestration."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from pharm_assistant.core.config import Settings
from pharm_assistant.models.schemas import DocumentSummary
from pharm_assistant.services.chunking import chunk_pages
from pharm_assistant.services.extraction import extract_pdf
from pharm_assistant.services.vector_store import ChromaDocumentStore


class DocumentValidationError(ValueError):
    """Raised when an upload does not meet the public API contract."""


def safe_filename(filename: str) -> str:
    """Keep a display-only basename without control characters."""

    basename = Path(filename.replace("\\", "/")).name
    basename = re.sub(r"[\x00-\x1f\x7f]", "", basename).strip()
    return basename[:255] or "document.pdf"


class DocumentService:
    def __init__(self, settings: Settings, store: ChromaDocumentStore) -> None:
        self._settings = settings
        self._store = store

    def ingest(self, filename: str, content: bytes) -> DocumentSummary:
        display_name = safe_filename(filename)
        if not display_name.lower().endswith(".pdf"):
            raise DocumentValidationError("Only PDF files are supported.")
        if not content:
            raise DocumentValidationError("The uploaded file is empty.")
        if len(content) > self._settings.max_upload_bytes:
            raise DocumentValidationError(
                f"PDF exceeds the {self._settings.max_upload_mb} MB upload limit."
            )
        if b"%PDF-" not in content[:1024]:
            raise DocumentValidationError("The uploaded file is not a valid PDF.")

        doc_id = hashlib.sha256(content).hexdigest()[:24]
        temp_path = self._settings.upload_dir / f".{doc_id}.tmp.pdf"
        final_path = self._settings.upload_dir / f"{doc_id}.pdf"
        temp_path.write_bytes(content)
        try:
            pages = extract_pdf(temp_path)
            chunks = chunk_pages(
                pages,
                doc_id=doc_id,
                filename=display_name,
                size_words=self._settings.chunk_size_words,
                overlap_words=self._settings.chunk_overlap_words,
            )
            summary = DocumentSummary(
                id=doc_id,
                filename=display_name,
                page_count=len(pages),
                chunk_count=len(chunks),
                size_bytes=len(content),
                created_at=datetime.now(UTC),
            )
            self._store.upsert_document(summary, chunks)
            temp_path.replace(final_path)
            return summary
        finally:
            temp_path.unlink(missing_ok=True)

    def list_documents(self) -> list[DocumentSummary]:
        return self._store.list_documents()

    def get_document(self, doc_id: str) -> DocumentSummary | None:
        return next((item for item in self._store.list_documents() if item.id == doc_id), None)

    def render_page(self, doc_id: str, page_number: int) -> bytes | None:
        """Rasterize one stored PDF page for in-app evidence review."""

        summary = self.get_document(doc_id)
        path = self.stored_pdf_path(doc_id)
        if summary is None or path is None:
            return None
        if page_number < 1 or page_number > summary.page_count:
            return None

        import pymupdf

        document = pymupdf.open(path)
        try:
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
            return pixmap.tobytes("png")
        finally:
            document.close()

    def stored_pdf_path(self, doc_id: str) -> Path | None:
        if self.get_document(doc_id) is None:
            return None
        upload_root = self._settings.upload_dir.resolve()
        path = (upload_root / f"{doc_id}.pdf").resolve()
        if path.parent != upload_root or not path.is_file():
            return None
        return path

    def delete(self, doc_id: str) -> bool:
        exists = any(item.id == doc_id for item in self._store.list_documents())
        self._store.delete_document(doc_id)
        (self._settings.upload_dir / f"{doc_id}.pdf").unlink(missing_ok=True)
        return exists
