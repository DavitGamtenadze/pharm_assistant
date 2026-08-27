from pharm_assistant.services.vector_store import RetrievedChunk, rerank_chunks


def _chunk(chunk_id: str, *, title: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        doc_id="doc",
        filename="who.pdf",
        page_number=12,
        section_title=title,
        text=text,
        score=score,
    )


def test_rerank_prefers_section_title_and_lexical_overlap() -> None:
    weaker_dense = _chunk(
        "generic",
        title="Introduction",
        text="This chapter introduces the overall programme.",
        score=0.82,
    )
    stronger_lexical = _chunk(
        "lasa",
        title="Look-alike sound-alike medicines",
        text="LASA names increase selection errors for high-alert medicines.",
        score=0.61,
    )

    ranked = rerank_chunks(
        "What does the document say about LASA high-alert medicines?",
        [weaker_dense, stronger_lexical],
        top_k=1,
    )

    assert ranked[0].id == "lasa"
