"""Page-aware extraction for PDFs, Office files, text, and images."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pharm_assistant.services.ocr import ocr_image_bytes, ocr_pdf_page

WORDS_PER_PAGE = 380
SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".doc",
    ".odt",
    ".rtf",
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".webp",
}

_PAGE_NUMBER_LINE = re.compile(
    r"^(?:page\s*)?\d{1,4}(?:\s*(?:of|/|-)\s*\d{1,4})?\.?$",
    re.IGNORECASE,
)
_TRAILING_PAGE_NUMBER = re.compile(
    r"(?:\s+(?:page\s*)?\d{1,4}(?:\s*(?:of|/|-)\s*\d{1,4})?)\.?\s*$",
    re.IGNORECASE,
)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_PRINT_ARTIFACT = re.compile(r"(?i)\b(?:high\s*risk)?\s*\d+\s*print\b")
_NAV_CRUMB = re.compile(r"^>+\s*")
_MARKDOWN_EMPHASIS = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_MARKDOWN_HEADING_PREFIX = re.compile(r"^#{1,6}\s+")
_PUNCTUATION = str.maketrans(
    {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
        "\u2022": "-",
        "\ufffd": " ",
    }
)


class DocumentExtractionError(ValueError):
    """Raised when a document cannot produce safe, usable text."""


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str
    title: str | None = None


def sanitize_extracted_text(value: str) -> str:
    """Remove converter artifacts that survive heading-aware chunking."""

    value = _HTML_COMMENT.sub(" ", value)
    value = _HTML_TAG.sub(" ", value)
    value = _PRINT_ARTIFACT.sub(" ", value)
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = _NAV_CRUMB.sub("", raw_line)
        line = _MARKDOWN_HEADING_PREFIX.sub("", line)
        line = _MARKDOWN_EMPHASIS.sub(r"\1", line)
        line = re.sub(r"[ \t]+", " ", line).strip(" -|")
        if line:
            lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(_PUNCTUATION)
    value = value.replace("\x00", " ")
    return sanitize_extracted_text(value)


def _line_key(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip().casefold()


def is_usable_text(value: str) -> bool:
    """Return whether extracted text is safe enough to index."""

    if len(value) < 40 or sum(char.isalnum() for char in value) < 20:
        return False
    printable = sum(
        char.isprintable() or unicodedata.category(char).startswith("Z") for char in value
    )
    return printable / max(len(value), 1) >= 0.9


def _repeated_edge_lines(texts: list[str], *, min_occurrences: int = 3) -> set[str]:
    """Collect short first/last lines that repeat across enough pages."""

    if len(texts) < min_occurrences:
        return set()

    counts: Counter[str] = Counter()
    for text in texts:
        lines = [line for line in text.splitlines() if line.strip()]
        seen: set[str] = set()
        for line in (*lines[:2], *lines[-2:]):
            key = _line_key(line)
            if not key or len(key) > 90 or key in seen:
                continue
            seen.add(key)
            counts[key] += 1
    return {key for key, count in counts.items() if count >= min_occurrences}


def _is_running_chrome(line: str, repeated: set[str]) -> bool:
    key = _line_key(line)
    if not key:
        return True
    if _PAGE_NUMBER_LINE.match(key):
        return True
    return key in repeated


def _repeated_prefixes(
    texts: list[str],
    *,
    word_count: int = 5,
    min_occurrences: int = 3,
) -> set[str]:
    """Collect short leading phrases that repeat across enough pages."""

    if len(texts) < min_occurrences:
        return set()
    counts: Counter[str] = Counter()
    for text in texts:
        words = text.split()
        if len(words) < word_count + 6:
            continue
        phrase = _line_key(" ".join(words[:word_count]))
        if 12 <= len(phrase) <= 90:
            counts[phrase] += 1
    return {phrase for phrase, count in counts.items() if count >= min_occurrences}


def _strip_prefix(text: str, prefixes: set[str]) -> str:
    words = text.split()
    if len(words) < 6:
        return text
    for length in range(min(10, len(words) - 5), 4, -1):
        phrase = _line_key(" ".join(words[:length]))
        if phrase in prefixes:
            return " ".join(words[length:]).strip()
    return text


def strip_running_chrome(texts: list[str]) -> list[str]:
    """Remove repeated headers, footers, and page-number chrome from page text."""

    repeated = _repeated_edge_lines(texts)
    prefixes = _repeated_prefixes(texts)
    cleaned: list[str] = []
    for text in texts:
        kept = [
            _TRAILING_PAGE_NUMBER.sub("", line).strip()
            for line in text.splitlines()
            if not _is_running_chrome(line, repeated)
        ]
        page_text = _strip_prefix("\n".join(kept).strip(), prefixes)
        page_text = _TRAILING_PAGE_NUMBER.sub("", page_text).strip()
        cleaned.append(sanitize_extracted_text(page_text))
    return cleaned


def extract_pdf(path: Path) -> list[ExtractedPage]:
    """Extract ordered pages as Markdown while retaining one-based page numbers."""

    try:
        import pymupdf4llm

        raw_pages: Any = pymupdf4llm.to_markdown(
            str(path),
            page_chunks=True,
            show_progress=False,
        )
    except Exception as exc:  # library raises several parser-specific exceptions
        msg = "The PDF could not be read. It may be encrypted, damaged, or unsupported."
        raise DocumentExtractionError(msg) from exc

    if not isinstance(raw_pages, list):
        msg = "The PDF extractor returned an unexpected result."
        raise DocumentExtractionError(msg)

    raw_texts: list[str] = []
    titles: list[str | None] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            raw_texts.append("")
            titles.append(None)
            continue
        raw_texts.append(_normalize_text(str(raw_page.get("text") or "")))
        metadata = raw_page.get("metadata") or {}
        titles.append(sanitize_extracted_text(str(metadata.get("title") or "")) or None)

    cleaned_texts = strip_running_chrome(raw_texts)
    pages = [
        ExtractedPage(page_number=page_number, text=text, title=title)
        for page_number, (text, title) in enumerate(
            zip(cleaned_texts, titles, strict=True),
            start=1,
        )
    ]

    pages = [
        _fill_empty_pdf_page(path, page) if not is_usable_text(page.text) else page
        for page in pages
    ]
    if not any(is_usable_text(page.text) for page in pages):
        msg = "No usable text was extracted, even after OCR."
        raise DocumentExtractionError(msg)
    return pages


def extract_document(path: Path, filename: str | None = None) -> list[ExtractedPage]:
    """Extract ordered pages from a supported medical document."""

    suffix = Path(filename or path.name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DocumentExtractionError(
            "Unsupported file type. Try PDF, Word, ODT, RTF, HTML, Markdown, text, or an image."
        )
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".doc":
        return extract_doc(path)
    if suffix == ".odt":
        return extract_odt(path)
    if suffix == ".rtf":
        return extract_rtf(path)
    if suffix in {".html", ".htm"}:
        return extract_html(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
        return extract_image(path)
    return extract_plain(path)


def extract_docx(path: Path) -> list[ExtractedPage]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = Document(str(path))
    except Exception as exc:
        raise DocumentExtractionError("The Word document could not be read.") from exc

    pages: list[list[str]] = [[]]
    for child in document.element.body:
        if child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
            block = "\n".join(row for row in rows if row.replace("|", "").strip())
            if block:
                pages[-1].append(block)
            continue
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, document)
        text = paragraph.text.strip()
        if text:
            pages[-1].append(text)
        if _docx_has_page_break(paragraph):
            pages.append([])

    texts = ["\n".join(part).strip() for part in pages if any(part)]
    extracted = _pages_from_texts(texts)
    if not extracted:
        raise DocumentExtractionError("The Word document did not contain usable text.")
    return extracted


def extract_doc(path: Path) -> list[ExtractedPage]:
    text = _normalize_text(_legacy_doc_text(path))
    extracted = _pages_from_texts([text] if text else [])
    if not extracted:
        raise DocumentExtractionError(
            "Could not read this .doc file. Save it as .docx, or convert it on a Mac with "
            "TextEdit / textutil."
        )
    return extracted


def extract_odt(path: Path) -> list[ExtractedPage]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("content.xml").decode("utf-8", errors="ignore")
    except Exception as exc:
        raise DocumentExtractionError("The OpenDocument file could not be read.") from exc
    text = _normalize_text(xml)
    extracted = _pages_from_texts([text] if text else [])
    if not extracted:
        raise DocumentExtractionError("The OpenDocument file did not contain usable text.")
    return extracted


def extract_rtf(path: Path) -> list[ExtractedPage]:
    from striprtf.striprtf import rtf_to_text

    try:
        text = _normalize_text(rtf_to_text(path.read_text(encoding="utf-8", errors="ignore")))
    except Exception as exc:
        raise DocumentExtractionError("The RTF file could not be read.") from exc
    extracted = _pages_from_texts([text] if text else [])
    if not extracted:
        raise DocumentExtractionError("The RTF file did not contain usable text.")
    return extracted


def extract_html(path: Path) -> list[ExtractedPage]:
    text = _normalize_text(path.read_text(encoding="utf-8", errors="ignore"))
    extracted = _pages_from_texts([text] if text else [])
    if not extracted:
        raise DocumentExtractionError("The HTML file did not contain usable text.")
    return extracted


def extract_plain(path: Path) -> list[ExtractedPage]:
    text = _normalize_text(path.read_text(encoding="utf-8", errors="ignore"))
    extracted = _pages_from_texts([text] if text else [])
    if not extracted:
        raise DocumentExtractionError("The text file did not contain usable text.")
    return extracted


def extract_image(path: Path) -> list[ExtractedPage]:
    text = _normalize_text(ocr_image_bytes(path.read_bytes()))
    if not is_usable_text(text):
        raise DocumentExtractionError("OCR could not read usable text from this image.")
    return [ExtractedPage(page_number=1, text=text)]


def _fill_empty_pdf_page(path: Path, page: ExtractedPage) -> ExtractedPage:
    try:
        text = _normalize_text(ocr_pdf_page(path, page.page_number))
    except Exception:
        return page
    if not is_usable_text(text):
        return page
    return ExtractedPage(page_number=page.page_number, text=text, title=page.title)


def _pages_from_texts(texts: list[str]) -> list[ExtractedPage]:
    cleaned = [sanitize_extracted_text(text) for text in texts if text.strip()]
    if len(cleaned) == 1 and len(cleaned[0].split()) > WORDS_PER_PAGE * 2:
        words = cleaned[0].split()
        cleaned = [
            " ".join(words[index : index + WORDS_PER_PAGE])
            for index in range(0, len(words), WORDS_PER_PAGE)
        ]
    pages = [
        ExtractedPage(page_number=number, text=text)
        for number, text in enumerate(cleaned, start=1)
        if is_usable_text(text)
    ]
    return pages


def _docx_has_page_break(paragraph: object) -> bool:
    xml = getattr(getattr(paragraph, "_p", None), "xml", "")
    return 'w:type="page"' in xml or "w:type='page'" in xml


def _legacy_doc_text(path: Path) -> str:
    converters = []
    if shutil.which("textutil"):
        converters.append(_convert_with_textutil)
    if shutil.which("antiword"):
        converters.append(_convert_with_antiword)
    for binary in ("soffice", "libreoffice"):
        if shutil.which(binary):
            converters.append(lambda current, tool=binary: _convert_with_soffice(current, tool))
            break
    for convert in converters:
        try:
            text = convert(path)
        except (OSError, subprocess.CalledProcessError, DocumentExtractionError):
            continue
        if is_usable_text(text):
            return text
    return _ole_doc_text(path)


def _convert_with_textutil(path: Path) -> str:
    with tempfile.TemporaryDirectory() as raw:
        output = Path(raw) / "document.txt"
        _run_fixed(shutil.which("textutil"), "-convert", "txt", "-output", str(output), str(path))
        return output.read_text(encoding="utf-8", errors="ignore")


def _convert_with_antiword(path: Path) -> str:
    completed = _run_fixed(shutil.which("antiword"), str(path))
    return completed.stdout.decode("utf-8", errors="ignore")


def _convert_with_soffice(path: Path, binary: str) -> str:
    with tempfile.TemporaryDirectory() as raw:
        _run_fixed(
            shutil.which(binary),
            "--headless",
            "--convert-to",
            "txt:Text",
            "--outdir",
            raw,
            str(path),
            timeout=90,
        )
        outputs = list(Path(raw).glob("*.txt"))
        if not outputs:
            raise DocumentExtractionError("LibreOffice did not produce a text file.")
        return outputs[0].read_text(encoding="utf-8", errors="ignore")


def _run_fixed(
    executable: str | None,
    *args: str,
    timeout: int = 60,
) -> subprocess.CompletedProcess[bytes]:
    if not executable:
        raise DocumentExtractionError("Converter is not available.")
    return subprocess.run(  # noqa: S603
        [executable, *args],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def _ole_doc_text(path: Path) -> str:
    import olefile

    if not olefile.isOleFile(str(path)):
        raise DocumentExtractionError("The uploaded file is not a valid Word document.")
    with olefile.OleFileIO(str(path)) as ole:
        if not ole.exists("WordDocument"):
            raise DocumentExtractionError("The Word document could not be read.")
        data = ole.openstream("WordDocument").read()
    decoded = data.decode("utf-16le", errors="ignore")
    cleaned = "".join(char if char.isprintable() or char in "\n\t " else " " for char in decoded)
    return re.sub(r" {2,}", " ", cleaned)
