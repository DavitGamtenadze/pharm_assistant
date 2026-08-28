from pathlib import Path

import pytest

from pharm_assistant.core.config import PROJECT_ROOT, Settings
from pharm_assistant.integrations.europe_pmc import EuropePmcClient
from pharm_assistant.models.schemas import QuestionRequest
from pharm_assistant.services.ai_eval import GenerationCase, score_generation_case
from pharm_assistant.services.documents import DocumentService
from pharm_assistant.services.embeddings import SentenceTransformerEmbedder
from pharm_assistant.services.generation import OpenAIGenerator
from pharm_assistant.services.qa import PromptBuilder, QuestionService
from pharm_assistant.services.vector_store import ChromaDocumentStore

pytestmark = pytest.mark.live_openai


def _settings_or_skip(tmp_path: Path) -> Settings:
    settings = Settings(data_dir=tmp_path, env="test")
    key = settings.openai_api_key.get_secret_value().strip() if settings.openai_api_key else ""
    if not key:
        pytest.skip("OPENAI_API_KEY is not configured.")
    settings.ensure_directories()
    return settings


@pytest.mark.asyncio
async def test_live_model_answers_and_refuses_missing_facts(tmp_path: Path) -> None:
    settings = _settings_or_skip(tmp_path)
    store = ChromaDocumentStore(None, SentenceTransformerEmbedder(settings.embedding_model))
    documents = DocumentService(settings, store)
    pdf = PROJECT_ROOT / "demo_documents" / "synthetic_clinical_trial_summary.pdf"
    summary = documents.ingest(pdf.name, pdf.read_bytes())
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
    supported = GenerationCase(
        id="live-primary-endpoint",
        question="What primary endpoint was reported?",
        document=pdf.name,
        must_include=("Example Symptom Score", "week 12"),
        expected_page=1,
    )
    unsupported = GenerationCase(
        id="live-missing-lab",
        question="What was the mean serum creatinine at baseline?",
        document=pdf.name,
        expect_fallback=True,
    )

    try:
        supported_result = await questions.answer(
            QuestionRequest(question=supported.question, document_ids=[summary.id])
        )
        unsupported_result = await questions.answer(
            QuestionRequest(question=unsupported.question, document_ids=[summary.id])
        )
    finally:
        await literature.close()
        await generator.close()

    assert score_generation_case(supported, supported_result).passed
    assert score_generation_case(unsupported, unsupported_result).passed
