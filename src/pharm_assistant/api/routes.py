"""FastAPI endpoint contracts."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from pharm_assistant.container import ServiceContainer, get_container
from pharm_assistant.core.config import Settings, get_settings
from pharm_assistant.core.rate_limit import RateLimiter, require_rate_limit
from pharm_assistant.core.security import require_api_key
from pharm_assistant.models.schemas import (
    DocumentListResponse,
    DocumentSummary,
    HealthResponse,
    QuestionRequest,
    QuestionResponse,
)
from pharm_assistant.services.documents import (
    DocumentValidationError,
    is_supported_filename,
    media_type_for,
)
from pharm_assistant.services.extraction import DocumentExtractionError
from pharm_assistant.services.generation import GenerationUnavailableError

health_router = APIRouter()
upload_limiter = RateLimiter(get_settings().upload_rate_limit)
question_limiter = RateLimiter(get_settings().question_rate_limit)
api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_api_key)],
)


@health_router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    services: Annotated[ServiceContainer, Depends(get_container)],
) -> HealthResponse:
    configured = services.generator.is_configured
    store_ready = await run_in_threadpool(services.store.ready)
    documents = await run_in_threadpool(services.documents.list_documents)
    ready = configured and store_ready
    return HealthResponse(
        status="ok" if ready else "degraded",
        openai_configured=configured,
        langfuse_enabled=services.observability.enabled,
        store_ready=store_ready,
        document_count=len(documents),
        embedding_model=settings.embedding_model,
        generation_model=settings.openai_model,
    )


@api_router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    services: Annotated[ServiceContainer, Depends(get_container)],
) -> DocumentListResponse:
    documents = await run_in_threadpool(services.documents.list_documents)
    return DocumentListResponse(documents=documents)


@api_router.post(
    "/documents",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    services: Annotated[ServiceContainer, Depends(get_container)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(description="A medical PDF, Word, text, or image file")],
    _: Annotated[None, Depends(require_rate_limit(upload_limiter))],
) -> DocumentSummary:
    filename = file.filename or "document.pdf"
    allowed_types = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
        "application/rtf",
        "text/rtf",
        "text/plain",
        "text/markdown",
        "text/html",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/webp",
        "application/octet-stream",
    }
    if file.content_type not in allowed_types and not is_supported_filename(filename):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Try PDF, Word, text, HTML, or an image.",
        )
    content = await file.read(settings.max_upload_bytes + 1)
    try:
        return await run_in_threadpool(
            services.documents.ingest,
            filename,
            content,
        )
    except (DocumentValidationError, DocumentExtractionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    finally:
        await file.close()


@api_router.get("/documents/{doc_id}/file")
async def download_document(
    services: Annotated[ServiceContainer, Depends(get_container)],
    doc_id: Annotated[str, Path(pattern=r"^[a-f0-9]{24}$")],
) -> FileResponse:
    summary = await run_in_threadpool(services.documents.get_document, doc_id)
    path = await run_in_threadpool(services.documents.stored_file_path, doc_id)
    if summary is None or path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return FileResponse(
        path,
        media_type=media_type_for(summary.filename),
        filename=summary.filename,
        content_disposition_type="inline",
    )


@api_router.get("/documents/{doc_id}/pages/{page_number}")
async def preview_document_page(
    services: Annotated[ServiceContainer, Depends(get_container)],
    doc_id: Annotated[str, Path(pattern=r"^[a-f0-9]{24}$")],
    page_number: Annotated[int, Path(ge=1, le=500)],
) -> Response:
    image = await run_in_threadpool(services.documents.render_page, doc_id, page_number)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document page not found.",
        )
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@api_router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    services: Annotated[ServiceContainer, Depends(get_container)],
    doc_id: Annotated[str, Path(pattern=r"^[a-f0-9]{24}$")],
) -> None:
    deleted = await run_in_threadpool(services.documents.delete, doc_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )


@api_router.post("/questions", response_model=QuestionResponse)
async def ask_question(
    request: QuestionRequest,
    services: Annotated[ServiceContainer, Depends(get_container)],
    _: Annotated[None, Depends(require_rate_limit(question_limiter))],
) -> QuestionResponse:
    if not request.document_ids and not request.include_literature:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one document or enable external literature.",
        )
    try:
        return await services.questions.answer(request)
    except GenerationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@api_router.post("/questions/stream")
async def ask_question_stream(
    request: QuestionRequest,
    services: Annotated[ServiceContainer, Depends(get_container)],
    _: Annotated[None, Depends(require_rate_limit(question_limiter))],
) -> StreamingResponse:
    if not request.document_ids and not request.include_literature:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one document or enable external literature.",
        )

    async def events() -> AsyncIterator[str]:
        try:
            async for kind, payload in services.questions.answer_stream(request):
                if kind == "token":
                    yield _sse({"type": "token", "text": payload})
                elif isinstance(payload, QuestionResponse):
                    yield _sse({"type": "done", **payload.model_dump(mode="json")})
        except GenerationUnavailableError as exc:
            yield _sse({"type": "error", "detail": str(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload)}\n\n"
