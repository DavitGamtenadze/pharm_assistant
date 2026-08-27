"""Application service composition."""

from __future__ import annotations

from functools import lru_cache

from pharm_assistant.core.config import Settings, get_settings
from pharm_assistant.core.observability import Observability
from pharm_assistant.integrations.europe_pmc import EuropePmcClient
from pharm_assistant.services.documents import DocumentService
from pharm_assistant.services.embeddings import SentenceTransformerEmbedder
from pharm_assistant.services.generation import OpenAIGenerator
from pharm_assistant.services.qa import PromptBuilder, QuestionService
from pharm_assistant.services.vector_store import ChromaDocumentStore


class ServiceContainer:
    """Construct shared, process-scoped service instances."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        embedder = SentenceTransformerEmbedder(settings.embedding_model)
        self.store = ChromaDocumentStore(settings.chroma_dir, embedder)
        self.documents = DocumentService(settings, self.store)
        self.observability = Observability(settings)
        self.generator = OpenAIGenerator(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
            callbacks=self.observability.callbacks,
        )
        self.literature = EuropePmcClient(cache_dir=settings.cache_dir)
        self.questions = QuestionService(
            store=self.store,
            generator=self.generator,
            literature=self.literature,
            prompt_builder=PromptBuilder(settings.prompt_path),
            max_context_chars=settings.max_context_chars,
        )

    async def close(self) -> None:
        await self.generator.close()
        await self.literature.close()
        self.observability.shutdown()


@lru_cache(maxsize=1)
def get_container() -> ServiceContainer:
    return ServiceContainer(get_settings())
