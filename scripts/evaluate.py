"""Run retrieval and optional live generation evaluations."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

import pymupdf

from pharm_assistant.core.config import PROJECT_ROOT, Settings
from pharm_assistant.integrations.europe_pmc import EuropePmcClient
from pharm_assistant.models.schemas import QuestionRequest
from pharm_assistant.services.ai_eval import (
    judge_groundedness,
    load_generation_cases,
    score_generation_case,
)
from pharm_assistant.services.documents import DocumentService
from pharm_assistant.services.embeddings import SentenceTransformerEmbedder
from pharm_assistant.services.extraction import extract_pdf
from pharm_assistant.services.generation import OpenAIGenerator
from pharm_assistant.services.qa import PromptBuilder, QuestionService
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


def _run_retrieval(directory: Path) -> bool:
    synthetic_cases = json.loads((PROJECT_ROOT / "evals" / "cases.json").read_text("utf-8"))
    official_cases = json.loads(
        (PROJECT_ROOT / "evals" / "official_cases.json").read_text("utf-8")
    )
    official_pdfs = _locate_official_pdfs()
    failed = False
    settings = Settings(data_dir=directory, top_k=1, env="test")
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
        "suite": "retrieval",
        "metric": f"page_hit@{settings.top_k}",
        "score": hits / len(synthetic_cases),
        "cases": details,
    }
    print(json.dumps(report, indent=2))
    if hits != len(synthetic_cases):
        failed = True

    runnable = [case for case in official_cases if case["document"] in official_pdfs]
    if not runnable:
        print(
            json.dumps(
                {
                    "suite": "official_retrieval",
                    "status": "skipped",
                    "reason": (
                        "WHO/NIH PDFs were not found under "
                        ".data/demo_documents or .data/uploads."
                    ),
                },
                indent=2,
            )
        )
        return failed

    ids: dict[str, str] = {}
    for key, path in official_pdfs.items():
        ids[key] = service.ingest(path.name, path.read_bytes()).id
    official_hits, official_details = _score_cases(store, ids, runnable, 8)
    official_report = {
        "suite": "official_retrieval",
        "metric": "page_hit@8",
        "score": official_hits / len(runnable),
        "cases": official_details,
    }
    print(json.dumps(official_report, indent=2))
    if official_hits != len(runnable):
        failed = True
    return failed


async def _run_generation(*, use_judge: bool, require_judge: bool) -> bool:
    settings = Settings(data_dir=PROJECT_ROOT / ".data" / "eval-generation", env="test")
    settings.ensure_directories()
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
        raise SystemExit("OPENAI_API_KEY is required for --generation.")

    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    store = ChromaDocumentStore(settings.chroma_dir, embedder)
    documents = DocumentService(settings, store)
    generator = OpenAIGenerator(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    literature = EuropePmcClient(cache_dir=settings.cache_dir)
    questions = QuestionService(
        store=store,
        generator=generator,
        literature=literature,
        prompt_builder=PromptBuilder(settings.prompt_path),
        max_context_chars=settings.max_context_chars,
    )
    cases = load_generation_cases(PROJECT_ROOT / "evals" / "generation_cases.json")
    demo_dir = PROJECT_ROOT / "demo_documents"
    ids: dict[str, str] = {}
    for filename in {case.document for case in cases}:
        path = demo_dir / filename
        if not path.is_file():
            raise SystemExit(f"Demo PDF missing: {path}")
        ids[filename] = documents.ingest(filename, path.read_bytes()).id

    scores = []
    try:
        for case in cases:
            response = await questions.answer(
                QuestionRequest(
                    question=case.question,
                    document_ids=[ids[case.document]],
                    top_k=8,
                )
            )
            judge = None
            if use_judge:
                judge = await judge_groundedness(
                    generator,
                    question=case.question,
                    answer=response.answer,
                    excerpts=[citation.excerpt for citation in response.citations],
                )
            scores.append(
                score_generation_case(
                    case,
                    response,
                    judge=judge,
                    require_judge=require_judge,
                )
            )
    finally:
        await literature.close()
        await generator.close()

    passed = sum(score.passed for score in scores)
    report = {
        "suite": "generation",
        "score": passed / len(scores),
        "passed": passed,
        "total": len(scores),
        "cases": [score.to_dict() for score in scores],
    }
    print(json.dumps(report, indent=2))
    return passed != len(scores)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and grounded generation.")
    parser.add_argument(
        "--generation",
        action="store_true",
        help="Call OpenAI on the committed demo PDFs and score answers.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Also ask the model whether each answer stays inside the evidence.",
    )
    parser.add_argument(
        "--strict-judge",
        action="store_true",
        help="Fail a case when the groundedness judge returns false.",
    )
    args = parser.parse_args()
    failed = False
    with tempfile.TemporaryDirectory(prefix="medical-doc-eval-") as directory:
        failed = _run_retrieval(Path(directory))
    if args.generation:
        failed = (
            asyncio.run(
                _run_generation(
                    use_judge=args.judge or args.strict_judge,
                    require_judge=args.strict_judge,
                )
            )
            or failed
        )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
