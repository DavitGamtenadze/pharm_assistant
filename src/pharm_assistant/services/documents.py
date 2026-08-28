"""Document lifecycle orchestration."""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, datetime
from pathlib import Path

from pharm_assistant.core.config import Settings
from pharm_assistant.models.schemas import DocumentSummary
from pharm_assistant.services.chunking import chunk_pages
from pharm_assistant.services.extraction import (
    SUPPORTED_SUFFIXES,
    extract_document,
)
from pharm_assistant.services.vector_store import ChromaDocumentStore

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


class DocumentValidationError(ValueError):
    """Raised when an upload does not meet the public API contract."""


def safe_filename(filename: str) -> str:
    """Keep a display-only basename without control characters."""

    basename = Path(filename.replace("\\", "/")).name
    basename = re.sub(r"[\x00-\x1f\x7f]", "", basename).strip()
    return basename[:255] or "document.pdf"


def media_type_for(filename: str) -> str:
    return MEDIA_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def is_supported_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_SUFFIXES


class DocumentService:
    def __init__(self, settings: Settings, store: ChromaDocumentStore) -> None:
        self._settings = settings
        self._store = store

    def ingest(self, filename: str, content: bytes) -> DocumentSummary:
        display_name = safe_filename(filename)
        suffix = Path(display_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise DocumentValidationError(
                "Unsupported file type. Try PDF, Word, ODT, RTF, HTML, Markdown, text, or an image."
            )
        if not content:
            raise DocumentValidationError("The uploaded file is empty.")
        if len(content) > self._settings.max_upload_bytes:
            raise DocumentValidationError(
                f"File exceeds the {self._settings.max_upload_mb} MB upload limit."
            )
        _validate_magic(suffix, content)

        doc_id = hashlib.sha256(content).hexdigest()[:24]
        temp_path = self._settings.upload_dir / f".{doc_id}.tmp{suffix}"
        final_path = self._settings.upload_dir / f"{doc_id}{suffix}"
        temp_path.write_bytes(content)
        try:
            pages = extract_document(temp_path, display_name)
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
        """Rasterize one stored page for in-app evidence review."""

        summary = self.get_document(doc_id)
        path = self.stored_file_path(doc_id)
        if summary is None or path is None:
            return None
        if page_number < 1 or page_number > summary.page_count:
            return None

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            import pymupdf

            document = pymupdf.open(path)
            try:
                page = document[page_number - 1]
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
                return pixmap.tobytes("png")
            finally:
                document.close()

        if suffix in IMAGE_SUFFIXES and page_number == 1:
            from PIL import Image

            image = Image.open(path).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        return None

    def stored_file_path(self, doc_id: str) -> Path | None:
        if self.get_document(doc_id) is None:
            return None
        upload_root = self._settings.upload_dir.resolve()
        matches = [
            path
            for path in upload_root.glob(f"{doc_id}.*")
            if path.is_file() and path.parent == upload_root
        ]
        return matches[0] if matches else None

    def stored_pdf_path(self, doc_id: str) -> Path | None:
        return self.stored_file_path(doc_id)

    def delete(self, doc_id: str) -> bool:
        exists = any(item.id == doc_id for item in self._store.list_documents())
        self._store.delete_document(doc_id)
        upload_root = self._settings.upload_dir.resolve()
        for path in upload_root.glob(f"{doc_id}.*"):
            if path.is_file() and path.parent == upload_root:
                path.unlink(missing_ok=True)
        return exists


def _validate_magic(suffix: str, content: bytes) -> None:
    head = content[:8]
    if suffix == ".pdf" and b"%PDF-" not in content[:1024]:
        raise DocumentValidationError("The uploaded file is not a valid PDF.")
    if suffix in {".docx", ".odt"} and not content.startswith(b"PK"):
        raise DocumentValidationError("The uploaded file is not a valid Office document.")
    if suffix == ".doc" and not content.startswith(b"\xd0\xcf\x11\xe0"):
        raise DocumentValidationError("The uploaded file is not a valid Word document.")
    if suffix == ".rtf" and b"{\\rtf" not in content[:64]:
        raise DocumentValidationError("The uploaded file is not valid RTF.")
    if suffix == ".png" and head[:8] != b"\x89PNG\r\n\x1a\n":
        raise DocumentValidationError("The uploaded file is not a valid PNG.")
    if suffix in {".jpg", ".jpeg"} and head[:2] != b"\xff\xd8":
        raise DocumentValidationError("The uploaded file is not a valid JPEG.")
