"""Retrieval, deterministic context assembly, and grounded answer validation."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from pharm_assistant.core.logging import get_logger, request_id_var
from pharm_assistant.integrations.europe_pmc import EuropePmcClient
from pharm_assistant.models.schemas import (
    Citation,
    CitationType,
    LiteratureArticle,
    QuestionRequest,
    QuestionResponse,
)
from pharm_assistant.services.extraction import sanitize_extracted_text
from pharm_assistant.services.generation import OpenAIGenerator
from pharm_assistant.services.vector_store import (
    ChromaDocumentStore,
    RetrievedChunk,
)

FALLBACK_ANSWER = "Not found in the documents."
SYSTEM_PROMPT = (
    "You are a medical document research assistant. Provide concise, evidence-grounded "
    "answers for informational and research use. Follow the supplied rules exactly. "
    "Do not diagnose, prescribe, or infer facts that are absent from the evidence."
)
SOURCE_MARKER = re.compile(r"\[(?:doc:[^\]\n]+|PMID:\d+|EPMC:[A-Z]+:[^\]\n]+)\]")


@dataclass(frozen=True, slots=True)
class ContextSource:
    label: str
    text: str
    citation: Citation


@dataclass(frozen=True, slots=True)
class RetrievedContext:
    local_chunks: list[RetrievedChunk]
    articles: list[LiteratureArticle]
    sources: list[ContextSource]
    started: float


class PromptBuilder:
    def __init__(self, template_path: Path) -> None:
        environment = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=select_autoescape(default=True),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._template = environment.get_template(template_path.name)

    def render(self, question: str, sources: list[ContextSource]) -> str:
        return self._template.render(question=question, sources=sources)


class QuestionService:
    def __init__(
        self,
        *,
        store: ChromaDocumentStore,
        generator: OpenAIGenerator,
        literature: EuropePmcClient,
        prompt_builder: PromptBuilder,
        max_context_chars: int,
    ) -> None:
        self._store = store
        self._generator = generator
        self._literature = literature
        self._prompt_builder = prompt_builder
        self._max_context_chars = max_context_chars
        self._logger = get_logger()

    async def answer(self, request: QuestionRequest) -> QuestionResponse:
        context = await self._retrieve(request)
        request_id = request_id_var.get()
        if not context.sources:
            return QuestionResponse(
                answer=FALLBACK_ANSWER,
                citations=[],
                request_id=request_id,
                latency_ms=_elapsed_ms(context.started),
            )

        prompt = self._prompt_builder.render(request.question, context.sources)
        generation = await self._generator.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            trace_metadata=self._trace_metadata(request, context, request_id),
        )
        answer, citations = _validate_answer(generation.text, context.sources)
        return self._finish(
            context,
            answer=answer,
            citations=citations,
            request_id=request_id,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
        )

    async def answer_stream(
        self,
        request: QuestionRequest,
    ) -> AsyncIterator[tuple[str, str] | tuple[str, QuestionResponse]]:
        context = await self._retrieve(request)
        request_id = request_id_var.get()
        if not context.sources:
            yield (
                "done",
                QuestionResponse(
                    answer=FALLBACK_ANSWER,
                    citations=[],
                    request_id=request_id,
                    latency_ms=_elapsed_ms(context.started),
                ),
            )
            return

        prompt = self._prompt_builder.render(request.question, context.sources)
        pieces: list[str] = []
        async for token in self._generator.astream(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            trace_metadata=self._trace_metadata(request, context, request_id),
        ):
            pieces.append(token)
            yield ("token", token)

        generated = "".join(pieces)
        answer, citations = _validate_answer(generated, context.sources)
        yield (
            "done",
            self._finish(
                context,
                answer=answer,
                citations=citations,
                request_id=request_id,
            ),
        )

    async def _retrieve(self, request: QuestionRequest) -> RetrievedContext:
        started = time.perf_counter()
        local_task = asyncio.to_thread(
            self._store.query,
            request.question,
            document_ids=request.document_ids,
            top_k=request.top_k,
        )

        if request.include_literature:
            local_chunks, literature = await asyncio.gather(
                local_task,
                self._literature.search(request.question, min(request.top_k, 5)),
            )
            articles = literature.articles
        else:
            local_chunks = await local_task
            articles = []

        return RetrievedContext(
            local_chunks=local_chunks,
            articles=articles,
            sources=self._assemble_sources(local_chunks, articles),
            started=started,
        )

    def _trace_metadata(
        self,
        request: QuestionRequest,
        context: RetrievedContext,
        request_id: str | None,
    ) -> dict[str, object]:
        return {
            "request_id": request_id,
            "document_count": len(request.document_ids),
            "retrieved_chunk_count": len(context.local_chunks),
            "literature_count": len(context.articles),
        }

    def _finish(
        self,
        context: RetrievedContext,
        *,
        answer: str,
        citations: list[Citation],
        request_id: str | None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> QuestionResponse:
        latency_ms = _elapsed_ms(context.started)
        self._logger.info(
            "question_answered",
            latency_ms=latency_ms,
            retrieved_chunk_ids=[chunk.id for chunk in context.local_chunks],
            retrieval_scores=[round(chunk.score, 4) for chunk in context.local_chunks],
            literature_count=len(context.articles),
            citation_count=len(citations),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            used_fallback=answer == FALLBACK_ANSWER,
        )
        return QuestionResponse(
            answer=answer,
            citations=citations,
            request_id=request_id,
            latency_ms=latency_ms,
        )

    def _assemble_sources(
        self,
        chunks: list[RetrievedChunk],
        articles: list[LiteratureArticle],
    ) -> list[ContextSource]:
        candidates = [_document_source(chunk) for chunk in chunks]
        candidates.extend(_literature_source(article) for article in articles if article.abstract)

        sources: list[ContextSource] = []
        remaining = self._max_context_chars
        for source in candidates:
            if remaining <= 0:
                break
            text = source.text[:remaining]
            if not text.strip():
                continue
            sources.append(
                ContextSource(
                    label=source.label,
                    text=text,
                    citation=source.citation,
                )
            )
            remaining -= len(text)
        return sources


def _document_source(chunk: RetrievedChunk) -> ContextSource:
    label = f"[doc:{chunk.doc_id} p.{chunk.page_number}]"
    text = sanitize_extracted_text(chunk.text)
    citation = Citation(
        id=chunk.id,
        type=CitationType.DOCUMENT,
        label=label,
        excerpt=text[:600],
        score=chunk.score,
        document_id=chunk.doc_id,
        filename=chunk.filename,
        page=chunk.page_number,
        title=sanitize_extracted_text(chunk.section_title) or None,
    )
    return ContextSource(label=label, text=text, citation=citation)


def _literature_source(article: LiteratureArticle) -> ContextSource:
    label = f"[PMID:{article.pmid}]" if article.pmid else f"[EPMC:{article.source}:{article.id}]"
    citation = Citation(
        id=f"{article.source.lower()}-{article.id}",
        type=CitationType.LITERATURE,
        label=label,
        excerpt=article.abstract[:600],
        title=article.title,
        external_id=article.id,
        source="Europe PMC",
        url=article.url,
    )
    details = " · ".join(
        part for part in (article.journal, str(article.year) if article.year else None) if part
    )
    text = f"{article.title}\n{details}\n{article.abstract}".strip()
    return ContextSource(label=label, text=text, citation=citation)


def _validate_answer(
    generated_text: str,
    sources: list[ContextSource],
) -> tuple[str, list[Citation]]:
    text = generated_text.strip()
    if text == FALLBACK_ANSWER:
        return FALLBACK_ANSWER, []

    allowed = {source.label: source.citation for source in sources}
    markers = set(SOURCE_MARKER.findall(text))
    if not markers or not markers.issubset(allowed):
        return FALLBACK_ANSWER, []

    citations = [allowed[source.label] for source in sources if source.label in markers]
    return text, list({citation.id: citation for citation in citations}.values())


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
