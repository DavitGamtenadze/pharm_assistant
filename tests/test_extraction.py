import pymupdf

from pharm_assistant.services.extraction import (
    extract_pdf,
    is_usable_text,
    sanitize_extracted_text,
    strip_running_chrome,
)

HEADER = "MEDICATION SAFETY IN HIGH-RISK SITUATIONS"


def _multi_page_pdf(tmp_path, texts: list[str]):
    document = pymupdf.open()
    for text in texts:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(48, 48, 560, 760), text, fontsize=11)
    path = tmp_path / "guideline.pdf"
    path.write_bytes(document.tobytes())
    document.close()
    return path


def test_sanitize_extracted_text_removes_converter_artifacts() -> None:
    dirty = (
        "High Risk29Print > Introduction\n"
        "<!-- Start of picture text -->ignored<!-- End of picture text -->\n"
        "<u>LASA</u> names increase selection errors."
    )

    cleaned = sanitize_extracted_text(dirty)

    assert "29Print" not in cleaned
    assert "<!--" not in cleaned
    assert "<u>" not in cleaned
    assert "LASA names increase selection errors" in cleaned
    assert sanitize_extracted_text("High Risk29Print") == ""
    assert sanitize_extracted_text("**2. OVERVIEW**") == "2. OVERVIEW"


def test_strip_running_chrome_removes_repeated_headers_and_page_numbers() -> None:
    pages = [
        f"{HEADER}\nHigh-alert medicines require independent double checks.\n1 of 4",
        f"{HEADER}\nLook-alike sound-alike names increase selection errors.\n2 of 4",
        f"{HEADER}\nA Manual of Operations should define local safety checks.\n3 of 4",
        f"{HEADER}\nStaff training should include high-risk situations.\n4 of 4",
    ]

    cleaned = strip_running_chrome(pages)

    assert all("MEDICATION SAFETY" not in page for page in cleaned)
    assert all("of 4" not in page for page in cleaned)
    assert "independent double checks" in cleaned[0]
    assert "Look-alike sound-alike" in cleaned[1]


def test_extract_pdf_keeps_page_numbers_and_drops_repeated_headers(tmp_path) -> None:
    path = _multi_page_pdf(
        tmp_path,
        [
            f"{HEADER}\nCover page with no usable body text.\n1 of 4",
            f"{HEADER}\nHigh-alert medicines require independent double checks.\n2 of 4",
            f"{HEADER}\nLook-alike sound-alike names increase selection errors.\n3 of 4",
            f"{HEADER}\nLocal procedures should define who performs the check.\n4 of 4",
        ],
    )

    pages = extract_pdf(path)

    assert [page.page_number for page in pages] == [1, 2, 3, 4]
    assert all(HEADER not in page.text for page in pages)
    assert "independent double checks" in pages[1].text
    assert is_usable_text(pages[1].text)
