from pharm_assistant.services.chunking import chunk_pages, split_sections
from pharm_assistant.services.extraction import ExtractedPage


def test_clinical_headings_are_preserved_with_page_metadata() -> None:
    pages = [
        ExtractedPage(
            page_number=3,
            text=(
                "MEDICATIONS\nAspirin 81 mg daily and metformin 500 mg twice daily.\n"
                "ASSESSMENT AND PLAN\nContinue monitoring renal function."
            ),
        )
    ]

    sections = split_sections(pages[0])
    chunks = chunk_pages(
        pages,
        doc_id="abc123",
        filename="sample.pdf",
        size_words=50,
        overlap_words=10,
    )

    assert [heading for heading, _ in sections] == ["Medications", "Assessment And Plan"]
    assert {chunk.page_number for chunk in chunks} == {3}
    assert {chunk.section_title for chunk in chunks} == {
        "Medications",
        "Assessment And Plan",
    }
    assert all(chunk.doc_id == "abc123" for chunk in chunks)


def test_introduction_is_treated_as_a_section_heading() -> None:
    page = ExtractedPage(
        page_number=12,
        text="Introduction\nHigh-risk situations relate to medication-related harm.",
    )

    sections = split_sections(page)

    assert sections[0][0] == "Introduction"
    assert "medication-related harm" in sections[0][1]


def test_numbered_guideline_headings_are_preserved() -> None:
    page = ExtractedPage(
        page_number=7,
        text=(
            "3 Provider and patient factors\n"
            "Independent double checks reduce administration errors.\n"
            "1.2 Eligibility\n"
            "Sites must document inclusion criteria in the MOP."
        ),
    )

    sections = split_sections(page)

    assert [heading for heading, _ in sections] == [
        "3 Provider and patient factors",
        "1.2 Eligibility",
    ]


def test_markdown_tables_are_kept_as_atomic_chunks() -> None:
    table = (
        "| Term | Meaning |\n"
        "| --- | --- |\n"
        "| LASA | Look-alike sound-alike |\n"
        "| DOAC | Direct oral anticoagulant |"
    )
    pages = [
        ExtractedPage(
            page_number=5,
            text=f"Abbreviations\n{table}\nNarrative text continues after the table.",
        )
    ]

    chunks = chunk_pages(
        pages,
        doc_id="who",
        filename="who.pdf",
        size_words=8,
        overlap_words=2,
    )
    table_chunks = [chunk for chunk in chunks if "Look-alike sound-alike" in chunk.text]

    assert len(table_chunks) == 1
    assert "| Term | Meaning |" in table_chunks[0].text
    assert "Narrative text continues" not in table_chunks[0].text


def test_long_sections_overlap_without_crossing_pages() -> None:
    pages = [
        ExtractedPage(page_number=1, text=" ".join(f"first{i}" for i in range(30))),
        ExtractedPage(page_number=2, text=" ".join(f"second{i}" for i in range(30))),
    ]

    chunks = chunk_pages(
        pages,
        doc_id="doc",
        filename="two-pages.pdf",
        size_words=20,
        overlap_words=5,
    )

    first_page = [chunk for chunk in chunks if chunk.page_number == 1]
    second_page = [chunk for chunk in chunks if chunk.page_number == 2]
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert "first15" in first_page[0].text and "first15" in first_page[1].text
    assert all("second" not in chunk.text for chunk in first_page)
