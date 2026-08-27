from pathlib import Path

from pharm_assistant.core.config import Settings
from pharm_assistant.core.observability import Observability, _contains_sensitive_content
from pharm_assistant.tooling import LANGCHAIN_TOOLS


def test_langchain_tools_have_stable_names() -> None:
    assert [tool.name for tool in LANGCHAIN_TOOLS] == [
        "search_medical_documents",
        "search_external_literature",
    ]


def test_langfuse_is_optional_and_content_keys_are_redacted(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, langfuse_enabled=False)
    observability = Observability(settings)

    assert observability.enabled is False
    assert list(observability.callbacks) == []
    assert _contains_sensitive_content("gen_ai.prompt.0.content") is True
    assert _contains_sensitive_content("gen_ai.usage.input_tokens") is False
