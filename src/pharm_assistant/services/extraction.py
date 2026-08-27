"""Page-aware PDF extraction."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    """Raised when a PDF cannot produce safe, usable text."""


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

    if not any(is_usable_text(page.text) for page in pages):
        msg = (
            "No usable text was extracted. Only text-based PDFs are supported; "
            "scanned documents require OCR."
        )
        raise DocumentExtractionError(msg)
    return pages
