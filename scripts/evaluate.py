"""Run synthetic and optional official-PDF retrieval evaluations."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pymupdf

from pharm_assistant.core.config import PROJECT_ROOT, Settings
from pharm_assistant.services.documents import DocumentService
from pharm_assistant.services.embeddings import SentenceTransformerEmbedder
from pharm_assistant.services.extraction import extract_pdf
from pharm_assistant.services.vector_store import ChromaDocumentStore

SYNTHETIC_PAGES = [
    (
        "MEDICATION STORAGE\n"
        "Unopened study medication must be stored between 2 and 8 degrees Celsius. "
        "Temperature excursions must be documented before the product is used."
    ),
    (
        "SAFETY REPORTING\n"
        "A serious adverse event must be escalated to the medical monitor within "
        "24 hours of site awareness. Follow-up information should be sent promptly."
    ),
    (
        "DOCUMENT CONTROL\n"
        "Superseded controlled documents are retained for seven years. Staff must "
        "use only the current approved version from the quality system."
    ),
]


def _build_pdf() -> bytes:
    document = pymupdf.open()
    for text in SYNTHETIC_PAGES:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text, fontsize=11)
    value = document.tobytes()
    document.close()
    return value


def _score_cases(
    store: ChromaDocumentStore,
    document_ids: dict[str, str],
    cases: list[dict[str, object]],
    top_k: int,
) -> tuple[int, list[dict[str, object]]]:
    hits = 0
    details: list[dict[str, object]] = []
    for case in cases:
        document_key = str(case.get("document") or "synthetic")
        doc_id = document_ids[document_key]
        results = store.query(
            str(case["question"]),
            document_ids=[doc_id],
            top_k=top_k,
        )
        pages = [result.page_number for result in results]
        expected = int(case["expected_page"])
        hit = expected in pages
        hits += int(hit)
        details.append(
            {
                "document": document_key,
                "question": case["question"],
                "expected_page": expected,
                "retrieved_pages": pages,
                "hit": hit,
            }
        )
    return hits, details


def _locate_official_pdfs() -> dict[str, Path]:
    found: dict[str, Path] = {}
    demo = PROJECT_ROOT / ".data" / "demo_documents"
    named = {
        "who": demo / "who_medication_safety_high_risk_situations.pdf",
        "nih": demo / "nih_manual_of_operations_guidelines.pdf",
    }
    for key, path in named.items():
        if path.is_file():
            found[key] = path
    if {"who", "nih"} <= found.keys():
        return found

    uploads = PROJECT_ROOT / ".data" / "uploads"
    for path in sorted(uploads.glob("*.pdf")):
        if path.name.startswith("."):
            continue
        try:
            first_page = extract_pdf(path)[0].text[:500].casefold()
        except Exception:
            first_page = ""
        if "who" not in found and "medication safety in high-risk" in first_page:
            found["who"] = path
        elif "nih" not in found and "manual of operations" in first_page:
            found["nih"] = path
    return found


def main() -> None:
    synthetic_cases = json.loads((PROJECT_ROOT / "evals" / "cases.json").read_text("utf-8"))
    official_cases = json.loads(
        (PROJECT_ROOT / "evals" / "official_cases.json").read_text("utf-8")
    )
    official_pdfs = _locate_official_pdfs()
    failed = False

    with tempfile.TemporaryDirectory(prefix="medical-doc-eval-") as directory:
        settings = Settings(data_dir=Path(directory), top_k=1)
        settings.ensure_directories()
        store = ChromaDocumentStore(
            None,
            SentenceTransformerEmbedder(settings.embedding_model),
        )
        service = DocumentService(settings, store)
        synthetic = service.ingest("synthetic-medical-handbook.pdf", _build_pdf())
        hits, details = _score_cases(
            store,
            {"synthetic": synthetic.id},
            [{**case, "document": "synthetic"} for case in synthetic_cases],
            settings.top_k,
        )
        report = {
            "metric": f"page_hit@{settings.top_k}",
            "score": hits / len(synthetic_cases),
            "cases": details,
            "note": "Synthetic content only; this is a regression check, not clinical validation.",
        }
        print(json.dumps(report, indent=2))
        if hits != len(synthetic_cases):
            failed = True

        runnable = [case for case in official_cases if case["document"] in official_pdfs]
        if not runnable:
            print(
                json.dumps(
                    {
                        "official": "skipped",
                        "reason": (
                            "WHO/NIH PDFs were not found under "
                            ".data/demo_documents or .data/uploads."
                        ),
                    },
                    indent=2,
                )
            )
        else:
            ids: dict[str, str] = {}
            for key, path in official_pdfs.items():
                ids[key] = service.ingest(path.name, path.read_bytes()).id
            official_hits, official_details = _score_cases(store, ids, runnable, 8)
            official_report = {
                "metric": "page_hit@8",
                "score": official_hits / len(runnable),
                "cases": official_details,
                "note": (
                    "Optional official-PDF retrieval check; "
                    "skipped when source files are absent."
                ),
            }
            print(json.dumps(official_report, indent=2))
            if official_hits != len(runnable):
                failed = True

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
