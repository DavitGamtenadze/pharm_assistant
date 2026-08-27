from pathlib import Path

import pytest

from pharm_assistant.models.schemas import (
    CitationType,
    LiteratureArticle,
    LiteratureSearchResponse,
    QuestionRequest,
)
from pharm_assistant.services.generation import GenerationResult
from pharm_assistant.services.qa import (
    FALLBACK_ANSWER,
    PromptBuilder,
    QuestionService,
)
from pharm_assistant.services.vector_store import RetrievedChunk


class FakeStore:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks

    def query(
        self,
        query: str,
        *,
        document_ids: list[str],
        top_k: int,
    ) -> list[RetrievedChunk]:
        del query, document_ids
        return self.chunks[:top_k]


class FakeGenerator:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        trace_metadata: dict[str, object] | None = None,
    ) -> GenerationResult:
        assert "medical document research assistant" in system_prompt
        assert "<context>" in user_prompt
        assert trace_metadata and "retrieved_chunk_count" in trace_metadata
        return GenerationResult(text=self.answer, input_tokens=100, output_tokens=20)


class FakeLiterature:
    def __init__(self, articles: list[LiteratureArticle] | None = None) -> None:
        self.articles = articles or []

    async def search(self, query: str, max_results: int) -> LiteratureSearchResponse:
        del query, max_results
        return LiteratureSearchResponse(articles=self.articles)


def _service(answer: str) -> QuestionService:
    chunk = RetrievedChunk(
        id="chunk-1",
        doc_id="abc123",
        filename="trial.pdf",
        page_number=4,
        section_title="Results",
        text="Results\nThe primary endpoint improved by 12 percent.",
        score=0.91,
    )
    prompt_path = Path(__file__).parents[1] / "prompts" / "answer.jinja"
    return QuestionService(
        store=FakeStore([chunk]),  # type: ignore[arg-type]
        generator=FakeGenerator(answer),  # type: ignore[arg-type]
        literature=FakeLiterature(),  # type: ignore[arg-type]
        prompt_builder=PromptBuilder(prompt_path),
        max_context_chars=4_000,
    )


@pytest.mark.asyncio
async def test_answer_returns_only_citations_used_by_the_model() -> None:
    service = _service("The primary endpoint improved by 12 percent [doc:abc123 p.4].")

    result = await service.answer(
        QuestionRequest(question="What was the endpoint result?", document_ids=["abc123"])
    )

    assert result.answer.endswith("[doc:abc123 p.4].")
    assert [citation.id for citation in result.citations] == ["chunk-1"]
    assert result.citations[0].page == 4


@pytest.mark.asyncio
async def test_document_citation_drops_converter_artifact_titles() -> None:
    chunk = RetrievedChunk(
        id="chunk-who",
        doc_id="ff09abf5fe4695abef8cc4b4",
        filename="who_medication_safety_high_risk_situations.pdf",
        page_number=12,
        section_title="High Risk29Print",
        text="High Risk29Print > Introduction\nLASA names increase selection errors.",
        score=0.51,
    )
    prompt_path = Path(__file__).parents[1] / "prompts" / "answer.jinja"
    service = QuestionService(
        store=FakeStore([chunk]),  # type: ignore[arg-type]
        generator=FakeGenerator(
            "LASA names increase selection errors [doc:ff09abf5fe4695abef8cc4b4 p.12]."
        ),  # type: ignore[arg-type]
        literature=FakeLiterature(),  # type: ignore[arg-type]
        prompt_builder=PromptBuilder(prompt_path),
        max_context_chars=4_000,
    )

    result = await service.answer(
        QuestionRequest(
            question="What does LASA stand for?",
            document_ids=["ff09abf5fe4695abef8cc4b4"],
        )
    )

    assert result.citations[0].title is None
    assert "29Print" not in result.citations[0].excerpt
    assert "LASA names increase selection errors" in result.citations[0].excerpt


@pytest.mark.asyncio
async def test_uncited_generation_is_replaced_with_exact_fallback() -> None:
    service = _service("The primary endpoint improved.")

    result = await service.answer(
        QuestionRequest(question="What was the endpoint result?", document_ids=["abc123"])
    )

    assert result.answer == FALLBACK_ANSWER
    assert result.citations == []


@pytest.mark.asyncio
async def test_external_literature_is_returned_as_structured_evidence() -> None:
    article = LiteratureArticle(
        id="12345678",
        source="MED",
        pmid="12345678",
        title="A controlled medical study",
        journal="Example Journal",
        year=2026,
        abstract="The intervention improved the primary endpoint.",
        url="https://europepmc.org/article/MED/12345678",
    )
    prompt_path = Path(__file__).parents[1] / "prompts" / "answer.jinja"
    service = QuestionService(
        store=FakeStore([]),  # type: ignore[arg-type]
        generator=FakeGenerator("The intervention improved the primary endpoint [PMID:12345678]."),  # type: ignore[arg-type]
        literature=FakeLiterature([article]),  # type: ignore[arg-type]
        prompt_builder=PromptBuilder(prompt_path),
        max_context_chars=4_000,
    )

    result = await service.answer(
        QuestionRequest(
            question="What happened to the primary endpoint?",
            include_literature=True,
        )
    )

    assert result.citations[0].type == CitationType.LITERATURE
    assert result.citations[0].external_id == "12345678"
