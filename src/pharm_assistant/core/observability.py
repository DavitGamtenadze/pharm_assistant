"""Optional Langfuse tracing with privacy-safe defaults."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.types import (
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanPatch,
)

from pharm_assistant.core.config import Settings
from pharm_assistant.core.logging import get_logger


def _contains_sensitive_content(attribute: str) -> bool:
    lowered = attribute.casefold()
    if ".usage." in lowered or lowered.endswith(("_tokens", ".model", ".name")):
        return False
    return any(
        marker in lowered
        for marker in (
            "prompt",
            "completion",
            "message",
            "content",
            "input",
            "output",
        )
    )


def redact_trace_content(
    *,
    params: MaskOtelSpansParams,
) -> MaskOtelSpansResult | None:
    """Remove prompt, completion, message, and tool payload attributes before export."""

    patches = {}
    for identifier, span in params.spans.items():
        sensitive_keys = tuple(key for key in span.attributes if _contains_sensitive_content(key))
        if sensitive_keys:
            patches[identifier] = OtelSpanPatch(
                delete_attributes=sensitive_keys,
                set_attributes={"app.content_redacted": True},
            )
    return MaskOtelSpansResult(span_patches=patches) if patches else None


class Observability:
    """Own the Langfuse client and LangChain callback lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self._client: Langfuse | None = None
        self._callbacks: tuple[BaseCallbackHandler, ...] = ()
        if not settings.langfuse_enabled:
            return

        public_key = (
            settings.langfuse_public_key.get_secret_value() if settings.langfuse_public_key else ""
        )
        secret_key = (
            settings.langfuse_secret_key.get_secret_value() if settings.langfuse_secret_key else ""
        )
        if not public_key or not secret_key:
            get_logger().warning("langfuse_disabled_missing_credentials")
            return

        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.env,
            tracing_enabled=True,
            mask_otel_spans=(None if settings.langfuse_capture_content else redact_trace_content),
        )
        self._callbacks = (CallbackHandler(public_key=public_key),)
        get_logger().info(
            "langfuse_enabled",
            content_capture=settings.langfuse_capture_content,
        )

    @property
    def callbacks(self) -> Sequence[BaseCallbackHandler]:
        return self._callbacks

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.flush()
            self._client.shutdown()
