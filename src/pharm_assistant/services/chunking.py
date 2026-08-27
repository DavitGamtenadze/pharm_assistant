"""Guideline-heading-aware, page-bounded text chunking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from pharm_assistant.services.extraction import ExtractedPage, is_usable_text

MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
NUMBERED_HEADING = re.compile(
    r"^\d+(?:\.\d+){0,4}[.)]?\s+[A-Z][A-Za-z0-9 ,/&()'%-]{2,80}$"
)
CLINICAL_HEADING = re.compile(
    r"^(?:"
    r"abbreviations|abstract|assessment(?: and plan)?|background|"
    r"chief complaint|clinical history|conclusions?|"
    r"contraindications?|diagnosis|discussion|dosage(?: and administration)?|"
    r"findings?|history of present illness|indications?|interactions?|"
    r"introduction|laboratory data|medications?|methods?|overview|"
    r"physical examination|precautions?|recommendations?|references|"
    r"results?|summary|warnings?"
    r")\s*:?\s*$",
    re.IGNORECASE,
)
TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    id: str
    doc_id: str
    filename: str
    page_number: int
    section_title: str
    text: str


def _is_table_line(line: str) -> bool:
    return bool(TABLE_LINE.match(line))


def _heading_from_line(line: str) -> str | None:
    if _is_table_line(line):
        return None
    markdown_match = MARKDOWN_HEADING.match(line)
    if markdown_match:
        return markdown_match.group(1).strip()
    if NUMBERED_HEADING.match(line.strip()):
        return line.strip()
    if CLINICAL_HEADING.match(line):
        return line.rstrip(":").strip().title()

    stripped = line.rstrip(":").strip()
    words = stripped.split()
    if (
        line.strip().endswith(":")
        and 1 <= len(words) <= 10
        and len(stripped) <= 90
        and not stripped.endswith((".", "?", "!"))
    ):
        return stripped
    if (
        1 <= len(words) <= 10
        and len(stripped) <= 90
        and any(char.isalpha() for char in stripped)
        and stripped.upper() == stripped
    ):
        return stripped.title()
    return None


def split_sections(page: ExtractedPage) -> list[tuple[str, str]]:
    """Split one page on Markdown, numbered guideline, or clinical headings."""

    default_heading = page.title or f"Page {page.page_number}"
    current_heading = default_heading
    current_lines: list[str] = []
    sections: list[tuple[str, str]] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_heading, text))
        current_lines.clear()

    for line in page.text.splitlines():
        heading = _heading_from_line(line)
        if heading:
            flush()
            current_heading = heading
        else:
            current_lines.append(line)
    flush()
    return sections


def _content_units(text: str) -> list[str]:
    """Keep markdown tables intact while splitting surrounding prose."""

    units: list[str] = []
    prose: list[str] = []
    table: list[str] = []

    def flush_prose() -> None:
        block = "\n".join(prose).strip()
        if block:
            units.append(block)
        prose.clear()

    def flush_table() -> None:
        block = "\n".join(table).strip()
        if block:
            units.append(block)
        table.clear()

    for line in text.splitlines():
        if _is_table_line(line):
            flush_prose()
            table.append(line)
        else:
            flush_table()
            prose.append(line)
    flush_prose()
    flush_table()
    return units


def _is_markdown_table(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and all(_is_table_line(line) for line in lines)


def _word_windows(text: str, *, size: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = size - overlap
    windows: list[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + size]
        if not window:
            break
        windows.append(" ".join(window))
        if start + size >= len(words):
            break
    return windows


def _windows_for_unit(text: str, *, size: int, overlap: int) -> list[str]:
    if _is_markdown_table(text):
        return [text]
    return _word_windows(text, size=size, overlap=overlap)


def chunk_pages(
    pages: list[ExtractedPage],
    *,
    doc_id: str,
    filename: str,
    size_words: int,
    overlap_words: int,
) -> list[DocumentChunk]:
    """Create deterministic chunks that never cross a page boundary."""

    if overlap_words >= size_words:
        msg = "Chunk overlap must be smaller than chunk size."
        raise ValueError(msg)

    chunks: list[DocumentChunk] = []
    for page in pages:
        if not is_usable_text(page.text):
            continue
        for section_index, (heading, section_text) in enumerate(split_sections(page)):
            window_index = 0
            for unit in _content_units(section_text):
                for window in _windows_for_unit(
                    unit, size=size_words, overlap=overlap_words
                ):
                    text = f"{heading}\n{window}".strip()
                    identity = (
                        f"{doc_id}:{page.page_number}:{section_index}:{window_index}:{text}"
                    )
                    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
                    chunks.append(
                        DocumentChunk(
                            id=chunk_id,
                            doc_id=doc_id,
                            filename=filename,
                            page_number=page.page_number,
                            section_title=heading,
                            text=text,
                        )
                    )
                    window_index += 1
    if not chunks:
        msg = "The document did not contain enough usable text to index."
        raise ValueError(msg)
    return chunks
