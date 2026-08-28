"""Free local OCR for scanned pages and images (RapidOCR / ONNX)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def ocr_image_bytes(image: bytes) -> str:
    result, _elapsed = _engine()(image)
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        if isinstance(item, list | tuple) and len(item) >= 2 and isinstance(item[1], str):
            text = item[1].strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def ocr_pdf_page(path: Path, page_number: int) -> str:
    import pymupdf

    document = pymupdf.open(path)
    try:
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0), alpha=False)
        return ocr_image_bytes(pixmap.tobytes("png"))
    finally:
        document.close()
