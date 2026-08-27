"""Typed request, response, and integration schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator


class DocumentSummary(BaseModel):
    id: str
    filename: str
    page_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    size_bytes: int = Field(ge=1)
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=8, ge=1, le=20)
    include_literature: bool = False

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            msg = "Question must contain at least three visible characters."
            raise ValueError(msg)
        return value

    @field_validator("document_ids")
    @classmethod
    def unique_document_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class CitationType(StrEnum):
    DOCUMENT = "document"
    LITERATURE = "literature"


class Citation(BaseModel):
    id: str
    type: CitationType
    label: str
    excerpt: str
    score: float | None = None
    document_id: str | None = None
    filename: str | None = None
    page: int | None = None
    title: str | None = None
    external_id: str | None = None
    source: str | None = None
    url: HttpUrl | None = None


class QuestionResponse(BaseModel):
    answer: str
    citations: list[Citation]
    request_id: str
    latency_ms: int = Field(ge=0)


class HealthResponse(BaseModel):
    status: str
    openai_configured: bool
    langfuse_enabled: bool
    store_ready: bool = True
    document_count: int = Field(default=0, ge=0)
    embedding_model: str
    generation_model: str


class LiteratureArticle(BaseModel):
    id: str
    source: str
    pmid: str | None = None
    title: str
    journal: str | None = None
    year: int | None = None
    abstract: str = ""
    doi: str | None = None
    url: HttpUrl


class LiteratureSearchResponse(BaseModel):
    articles: list[LiteratureArticle]
    error: str | None = None
    cached: bool = False
