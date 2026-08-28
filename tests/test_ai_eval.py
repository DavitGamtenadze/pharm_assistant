from pharm_assistant.models.schemas import Citation, CitationType, QuestionResponse
from pharm_assistant.services.ai_eval import GenerationCase, score_generation_case
from pharm_assistant.services.qa import FALLBACK_ANSWER


def _response(answer: str, *, page: int | None = 1) -> QuestionResponse:
    citations = []
    if page is not None and answer != FALLBACK_ANSWER:
        citations.append(
            Citation(
                id="chunk-1",
                type=CitationType.DOCUMENT,
                label="[doc:abc123 p.1]",
                excerpt="The primary endpoint was change in the Example Symptom Score at week 12.",
                document_id="abc123",
                filename="trial.pdf",
                page=page,
            )
        )
    return QuestionResponse(
        answer=answer,
        citations=citations,
        request_id="test",
        latency_ms=12,
    )


def test_supported_answer_requires_fact_citation_and_page() -> None:
    case = GenerationCase(
        id="trial-primary-endpoint",
        question="What primary endpoint was reported?",
        document="trial.pdf",
        must_include=("Example Symptom Score", "week 12"),
        expected_page=1,
    )
    score = score_generation_case(
        case,
        _response(
            "The primary endpoint was the Example Symptom Score at week 12 [doc:abc123 p.1]."
        ),
    )

    assert score.passed
    assert score.checks["expected_page"]


def test_missing_fact_fails() -> None:
    case = GenerationCase(
        id="trial-primary-endpoint",
        question="What primary endpoint was reported?",
        document="trial.pdf",
        must_include=("Example Symptom Score",),
        expected_page=1,
    )
    score = score_generation_case(
        case,
        _response("A symptom score improved [doc:abc123 p.1]."),
    )

    assert not score.passed
    assert score.checks["includes:Example Symptom Score"] is False


def test_unsupported_question_must_use_exact_fallback() -> None:
    case = GenerationCase(
        id="unsupported-lab-value",
        question="What was the mean serum creatinine?",
        document="trial.pdf",
        expect_fallback=True,
    )
    score = score_generation_case(case, _response(FALLBACK_ANSWER, page=None))

    assert score.passed
    assert score.checks["fallback"]
    assert score.checks["no_citations"]


def test_invented_answer_without_citation_fails_supported_case() -> None:
    case = GenerationCase(
        id="trial-primary-endpoint",
        question="What primary endpoint was reported?",
        document="trial.pdf",
        must_include=("Example Symptom Score",),
        expected_page=1,
    )
    score = score_generation_case(case, _response(FALLBACK_ANSWER, page=None))

    assert not score.passed
    assert "expected a cited answer" in score.failures


def test_judge_can_fail_a_case_when_required() -> None:
    case = GenerationCase(
        id="trial-primary-endpoint",
        question="What primary endpoint was reported?",
        document="trial.pdf",
        must_include=("Example Symptom Score",),
        expected_page=1,
    )
    score = score_generation_case(
        case,
        _response("The primary endpoint was the Example Symptom Score [doc:abc123 p.1]."),
        judge={"grounded": False, "reason": "added an unstated dose"},
        require_judge=True,
    )

    assert not score.passed
    assert score.checks["judge_grounded"] is False
