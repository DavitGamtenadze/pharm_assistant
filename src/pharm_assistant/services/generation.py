"""Grounded-answer generation through the OpenAI Responses API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import SecretStr


class GenerationUnavailableError(RuntimeError):
    """Raised when the configured OpenAI model cannot answer."""


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class OpenAIGenerator:
    def __init__(
        self,
        api_key: SecretStr | None,
        model: str,
        timeout_seconds: float,
        callbacks: Sequence[BaseCallbackHandler] = (),
    ) -> None:
        self.model = model
        key = api_key.get_secret_value().strip() if api_key else ""
        self._callbacks = list(callbacks)
        self._client: ChatOpenAI | None = (
            ChatOpenAI(
                model=model,
                api_key=SecretStr(key),
                timeout=timeout_seconds,
                max_retries=2,
                max_completion_tokens=2_000,
                reasoning_effort="low",
                verbosity="low",
                use_responses_api=True,
                store=False,
            )
            if key
            else None
        )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        trace_metadata: dict[str, Any] | None = None,
    ) -> GenerationResult:
        if self._client is None:
            raise GenerationUnavailableError(
                "OPENAI_API_KEY is not configured. Add it to .env before asking questions."
            )
        try:
            response = await self._client.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ],
                config={
                    "callbacks": self._callbacks,
                    "run_name": "grounded_medical_answer",
                    "metadata": trace_metadata or {},
                },
            )
            text = response.text.strip()
            finish_reason = response.response_metadata.get("finish_reason")
            response_status = response.response_metadata.get("status")
            if finish_reason in {"length", "max_tokens"} or response_status == "incomplete":
                raise GenerationUnavailableError(
                    "OpenAI reached the output limit before completing a grounded answer."
                )
            if not text:
                raise GenerationUnavailableError("OpenAI returned an empty answer.")
            usage = response.usage_metadata or {}
            return GenerationResult(
                text=text,
                input_tokens=_optional_int(usage.get("input_tokens")),
                output_tokens=_optional_int(usage.get("output_tokens")),
            )
        except (OpenAIError, ValueError) as exc:
            msg = f"The configured OpenAI model '{self.model}' could not answer."
            raise GenerationUnavailableError(msg) from exc

    async def astream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        trace_metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        if self._client is None:
            raise GenerationUnavailableError(
                "OPENAI_API_KEY is not configured. Add it to .env before asking questions."
            )
        try:
            saw_text = False
            async for chunk in self._client.astream(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ],
                config={
                    "callbacks": self._callbacks,
                    "run_name": "grounded_medical_answer",
                    "metadata": trace_metadata or {},
                },
            ):
                finish_reason = chunk.response_metadata.get("finish_reason")
                response_status = chunk.response_metadata.get("status")
                if finish_reason in {"length", "max_tokens"} or response_status == "incomplete":
                    raise GenerationUnavailableError(
                        "OpenAI reached the output limit before completing a grounded answer."
                    )
                text = _chunk_text(chunk.content)
                if text:
                    saw_text = True
                    yield text
            if not saw_text:
                raise GenerationUnavailableError("OpenAI returned an empty answer.")
        except (OpenAIError, ValueError) as exc:
            msg = f"The configured OpenAI model '{self.model}' could not answer."
            raise GenerationUnavailableError(msg) from exc

    async def close(self) -> None:
        if self._client is not None:
            root_client = self._client.root_async_client
            if root_client is not None:
                await root_client.close()


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _chunk_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""
