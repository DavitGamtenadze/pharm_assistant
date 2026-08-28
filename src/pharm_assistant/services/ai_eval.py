"""Score grounded answers against expected facts, citations, and fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pharm_assistant.models.schemas import Citation, QuestionResponse
from pharm_assistant.services.qa import FALLBACK_ANSWER, SOURCE_MARKER


@dataclass(frozen=True, slots=True)
class GenerationCase:
    id: str
    question: str
    document: str
    expect_fallback: bool = False
    must_include: tuple[str, ...] = ()
    must_not_include: tuple[str, ...] = ()
    expected_page: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GenerationCase:
        return cls(
            id=str(raw["id"]),
            question=str(raw["question"]),
            document=str(raw["document"]),
            expect_fallback=bool(raw.get("expect_fallback", False)),
            must_include=tuple(str(item) for item in raw.get("must_include", [])),
            must_not_include=tuple(str(item) for item in raw.get("must_not_include", [])),
            expected_page=(
                int(raw["expected_page"]) if raw.get("expected_page") is not None else None
            ),
        )


@dataclass(slots=True)
class CaseScore:
    case_id: str
    passed: bool
    checks: dict[str, bool]
    answer: str
    cited_pages: list[int]
    latency_ms: int
    judge: dict[str, Any] | None = None
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.case_id,
            "passed": self.passed,
            "checks": self.checks,
            "answer": self.answer,
            "cited_pages": self.cited_pages,
            "latency_ms": self.latency_ms,
            "failures": self.failures,
        }
        if self.judge is not None:
            payload["judge"] = self.judge
        return payload


def load_generation_cases(path: Any) -> list[GenerationCase]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    return [GenerationCase.from_dict(item) for item in raw_cases]


def score_generation_case(
    case: GenerationCase,
    response: QuestionResponse,
    *,
    judge: dict[str, Any] | None = None,
    require_judge: bool = False,
) -> CaseScore:
    answer = response.answer.strip()
    cited_pages = [citation.page for citation in response.citations if citation.page is not None]
    checks: dict[str, bool] = {}
    failures: list[str] = []

    used_fallback = answer == FALLBACK_ANSWER
    checks["fallback"] = used_fallback is case.expect_fallback
    if not checks["fallback"]:
        expected = FALLBACK_ANSWER if case.expect_fallback else "a cited answer"
        failures.append(f"expected {expected}")

    if case.expect_fallback:
        checks["no_citations"] = response.citations == []
        if not checks["no_citations"]:
            failures.append("fallback answers must not include citations")
    else:
        checks["has_citation"] = bool(response.citations)
        if not checks["has_citation"]:
            failures.append("supported answers must cite a source")
        checks["citation_markers"] = _markers_match_citations(answer, response.citations)
        if not checks["citation_markers"]:
            failures.append("answer markers do not match returned citations")
        for phrase in case.must_include:
            key = f"includes:{phrase}"
            checks[key] = phrase.casefold() in answer.casefold()
            if not checks[key]:
                failures.append(f"missing required phrase {phrase!r}")
        for phrase in case.must_not_include:
            key = f"excludes:{phrase}"
            checks[key] = phrase.casefold() not in answer.casefold()
            if not checks[key]:
                failures.append(f"forbidden phrase {phrase!r} appeared")
        if case.expected_page is not None:
            checks["expected_page"] = case.expected_page in cited_pages
            if not checks["expected_page"]:
                failures.append(
                    f"expected page {case.expected_page}, cited {cited_pages or 'none'}"
                )

    if judge is not None:
        grounded = bool(judge.get("grounded"))
        checks["judge_grounded"] = grounded
        if require_judge and not grounded:
            failures.append(str(judge.get("reason") or "judge marked the answer ungrounded"))

    passed = all(checks.values())
    return CaseScore(
        case_id=case.id,
        passed=passed,
        checks=checks,
        answer=answer,
        cited_pages=cited_pages,
        latency_ms=response.latency_ms,
        judge=judge,
        failures=failures,
    )


def _markers_match_citations(answer: str, citations: list[Citation]) -> bool:
    markers = set(SOURCE_MARKER.findall(answer))
    labels = {citation.label for citation in citations}
    return bool(markers) and markers == labels


async def judge_groundedness(
    generator: Any,
    *,
    question: str,
    answer: str,
    excerpts: list[str],
) -> dict[str, Any]:
    """Ask the model whether the answer stays inside the retrieved excerpts."""

    evidence = "\n\n".join(f"<excerpt>{item}</excerpt>" for item in excerpts) or "<none/>"
    prompt = (
        "Decide if the answer is fully supported by the excerpts. "
        "Return only JSON with keys grounded (boolean), complete (boolean), "
        "and reason (short string).\n\n"
        f"<question>{question}</question>\n"
        f"<answer>{answer}</answer>\n"
        f"<evidence>\n{evidence}\n</evidence>"
    )
    result = await generator.generate(
        system_prompt=(
            "You are grading a retrieval-grounded medical assistant. "
            "Mark grounded true only if every medical claim is supported by the excerpts. "
            "Do not reward extra facts."
        ),
        user_prompt=prompt,
        trace_metadata={"eval": "groundedness_judge"},
    )
    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError:
        return {"grounded": False, "complete": False, "reason": "judge returned non-JSON"}
    return {
        "grounded": bool(payload.get("grounded")),
        "complete": bool(payload.get("complete")),
        "reason": str(payload.get("reason") or ""),
    }
