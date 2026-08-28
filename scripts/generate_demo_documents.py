"""Generate fictional, PHI-free medical PDFs for local demonstrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pharm_assistant.core.config import PROJECT_ROOT


@dataclass(frozen=True)
class DemoDocument:
    filename: str
    title: str
    subtitle: str
    pages: tuple[tuple[str, str], ...]


DOCUMENTS = (
    DemoDocument(
        filename="synthetic_clinical_trial_summary.pdf",
        title="MDX-101 Phase II Study Summary",
        subtitle="Fictional randomized controlled study",
        pages=(
            (
                "STUDY DESIGN",
                "This fictional phase II study enrolled 120 adults with Example Syndrome. "
                "Participants were randomized 1:1 to MDX-101 or placebo for 12 weeks. "
                "The study was double-blind and conducted at eight simulated sites.\n\n"
                "The primary endpoint was change from baseline in the Example Symptom "
                "Score at week 12. Secondary endpoints included response rate, quality of "
                "life, and treatment-emergent adverse events.",
            ),
            (
                "EFFICACY RESULTS",
                "At week 12, the fictional mean reduction in Example Symptom Score was "
                "8.4 points in the MDX-101 group and 3.1 points in the placebo group. "
                "The estimated between-group difference was 5.3 points (95% confidence "
                "interval 3.8 to 6.8).\n\n"
                "A predefined response was observed in 62% of MDX-101 participants and "
                "34% of placebo participants. These values exist only to test retrieval "
                "and citation behavior.",
            ),
            (
                "SAFETY RESULTS",
                "The most frequently recorded fictional adverse events with MDX-101 were "
                "nausea (12%), headache (9%), and fatigue (7%). One serious adverse event "
                "occurred in each study group; neither was assessed as related to study "
                "treatment. No deaths were reported.\n\n"
                "The simulated dataset is too small and too short to establish clinical "
                "safety. It must never be used for treatment decisions.",
            ),
        ),
    ),
    DemoDocument(
        filename="synthetic_medication_monograph.pdf",
        title="Examplevir Research Monograph",
        subtitle="Fictional investigational product information",
        pages=(
            (
                "DESCRIPTION AND INDICATION",
                "Examplevir is a fictional oral investigational compound created for this "
                "software demonstration. It has no approved indication and must not be "
                "dispensed, prescribed, or administered.\n\n"
                "For retrieval testing, the simulated dosage form is described as a "
                "50 mg blue film-coated tablet supplied in bottles of 30 tablets.",
            ),
            (
                "STORAGE AND HANDLING",
                "Unopened fictional Examplevir bottles should be stored between 2 and "
                "8 degrees Celsius in the demo scenario. Keep the bottle closed and "
                "protected from light. A simulated temperature excursion must be "
                "documented and reviewed before the demo product is marked usable.\n\n"
                "These handling instructions describe a nonexistent product and are not "
                "applicable to any real medicine.",
            ),
            (
                "WARNINGS AND INTERACTIONS",
                "The demo monograph lists severe fictional renal impairment as an "
                "exclusion criterion. It also states that strong Example Enzyme inducers "
                "were prohibited in the simulated protocol because exposure could be "
                "reduced.\n\n"
                "No real contraindication, interaction, dose, or safety conclusion may be "
                "inferred from this synthetic document.",
            ),
        ),
    ),
    DemoDocument(
        filename="synthetic_safety_reporting_sop.pdf",
        title="Safety Event Reporting SOP",
        subtitle="Fictional research-site procedure",
        pages=(
            (
                "PURPOSE AND SCOPE",
                "This synthetic procedure describes how a fictional research site records "
                "and escalates safety events during a demonstration study. It applies only "
                "to the generated demo records packaged with this software.",
            ),
            (
                "SERIOUS EVENT ESCALATION",
                "A serious adverse event in the fictional workflow must be escalated to "
                "the simulated medical monitor within 24 hours of site awareness. The "
                "initial report may be incomplete, but available facts and the participant "
                "identifier must be provided. Follow-up information is submitted promptly.",
            ),
            (
                "DOCUMENT CONTROL",
                "The fictional quality team reviews this procedure every two years. "
                "Superseded controlled copies are retained for seven years in the demo "
                "archive. Printed copies are uncontrolled unless their status is verified "
                "against the current approved version.",
            ),
        ),
    ),
)


def _add_page(
    document: pymupdf.Document,
    *,
    document_title: str,
    section_title: str,
    body: str,
    page_number: int,
) -> None:
    page = document.new_page(width=595, height=842)
    page.draw_rect(pymupdf.Rect(0, 0, 595, 96), color=None, fill=(0.04, 0.33, 0.26))
    page.insert_text(
        (48, 43),
        document_title,
        fontname="hebo",
        fontsize=15,
        color=(1, 1, 1),
    )
    page.insert_text(
        (48, 70),
        "SYNTHETIC DEMO — NOT FOR CLINICAL USE",
        fontname="hebo",
        fontsize=8,
        color=(0.75, 0.93, 0.86),
    )
    page.insert_text(
        (48, 142),
        section_title,
        fontname="hebo",
        fontsize=17,
        color=(0.05, 0.28, 0.23),
    )
    page.draw_line(
        pymupdf.Point(48, 158),
        pymupdf.Point(547, 158),
        color=(0.78, 0.86, 0.83),
    )
    page.insert_textbox(
        pymupdf.Rect(48, 184, 547, 730),
        body,
        fontname="helv",
        fontsize=11,
        lineheight=1.55,
        color=(0.12, 0.19, 0.17),
    )
    page.insert_text(
        (48, 798),
        "Fictional content generated for Medical Document Assistant testing",
        fontname="helv",
        fontsize=8,
        color=(0.42, 0.49, 0.46),
    )
    page.insert_text(
        (520, 798),
        f"Page {page_number}",
        fontname="helv",
        fontsize=8,
        color=(0.42, 0.49, 0.46),
    )


def generate(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for specification in DOCUMENTS:
        document = pymupdf.open()
        document.set_metadata(
            {
                "title": specification.title,
                "author": "Medical Document Assistant demo generator",
                "subject": specification.subtitle,
                "keywords": "synthetic, demo, medical document assistant",
            }
        )
        for page_number, (heading, body) in enumerate(specification.pages, start=1):
            _add_page(
                document,
                document_title=specification.title,
                section_title=heading,
                body=body,
                page_number=page_number,
            )
        destination = output_dir / specification.filename
        document.save(destination, garbage=4, deflate=True)
        document.close()
        generated.append(destination)
    return generated


def main() -> None:
    for path in generate(PROJECT_ROOT / "demo_documents"):
        print(path.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
