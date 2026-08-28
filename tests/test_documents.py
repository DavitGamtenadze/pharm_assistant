from pathlib import Path

import pymupdf

from pharm_assistant.core.config import Settings
from pharm_assistant.models.schemas import DocumentSummary
from pharm_assistant.services.chunking import DocumentChunk
from pharm_assistant.services.documents import DocumentService, DocumentValidationError


class RecordingStore:
    def __init__(self) -> None:
        self.summaries: dict[str, DocumentSummary] = {}
        self.chunks: dict[str, list[DocumentChunk]] = {}

    def upsert_document(
        self,
        summary: DocumentSummary,
        chunks: list[DocumentChunk],
    ) -> None:
        self.summaries[summary.id] = summary
        self.chunks[summary.id] = chunks

    def list_documents(self) -> list[DocumentSummary]:
        return list(self.summaries.values())

    def delete_document(self, doc_id: str) -> None:
        self.summaries.pop(doc_id, None)
        self.chunks.pop(doc_id, None)


def _pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        (
            "CLINICAL SUMMARY\n"
            "The participant received study medication once daily. "
            "Renal function was monitored throughout the study."
        ),
    )
    value = document.tobytes()
    document.close()
    return value


def test_document_service_indexes_and_deletes_a_pdf(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, chunk_size_words=50, chunk_overlap_words=10)
    settings.ensure_directories()
    store = RecordingStore()
    service = DocumentService(settings, store)  # type: ignore[arg-type]

    summary = service.ingest("../../unsafe-name.pdf", _pdf_bytes())

    assert summary.filename == "unsafe-name.pdf"
    assert summary.page_count == 1
    assert summary.chunk_count >= 1
    assert (settings.upload_dir / f"{summary.id}.pdf").exists()
    assert service.stored_pdf_path(summary.id) == settings.upload_dir / f"{summary.id}.pdf"
    assert service.delete(summary.id) is True
    assert service.stored_pdf_path(summary.id) is None
    assert not (settings.upload_dir / f"{summary.id}.pdf").exists()


def test_document_service_rejects_non_pdf_content(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    service = DocumentService(settings, RecordingStore())  # type: ignore[arg-type]

    try:
        service.ingest("notes.pdf", b"not a pdf")
    except DocumentValidationError as exc:
        assert "valid PDF" in str(exc)
    else:
        raise AssertionError("Invalid PDF content should be rejected.")


def test_document_service_indexes_a_docx(tmp_path: Path) -> None:
    from docx import Document

    settings = Settings(data_dir=tmp_path, chunk_size_words=50, chunk_overlap_words=10)
    settings.ensure_directories()
    service = DocumentService(settings, RecordingStore())  # type: ignore[arg-type]
    path = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph(
        "The participant received study medication once daily. "
        "Renal function was monitored throughout the study."
    )
    document.save(path)

    summary = service.ingest("trial-notes.docx", path.read_bytes())

    assert summary.filename == "trial-notes.docx"
    assert summary.page_count >= 1
    assert (settings.upload_dir / f"{summary.id}.docx").exists()
    assert service.stored_file_path(summary.id) == settings.upload_dir / f"{summary.id}.docx"
    assert service.delete(summary.id) is True
    assert service.stored_file_path(summary.id) is None


def test_document_service_rejects_unknown_types(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    service = DocumentService(settings, RecordingStore())  # type: ignore[arg-type]

    try:
        service.ingest("secrets.xlsx", b"not a spreadsheet")
    except DocumentValidationError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("Unknown types should be rejected.")
