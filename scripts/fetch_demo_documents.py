"""Download a small, license-documented medical demo corpus.

External PDFs are stored under the gitignored ``.data/demo_documents`` directory
and are not redistributed by this repository.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from pharm_assistant.core.config import PROJECT_ROOT

MAX_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ExternalDocument:
    filename: str
    title: str
    publisher: str
    url: str
    landing_page: str
    license_note: str


DOCUMENTS = (
    ExternalDocument(
        filename="who_medication_safety_high_risk_situations.pdf",
        title="Medication Safety in High-risk Situations",
        publisher="World Health Organization",
        url=(
            "https://iris.who.int/server/api/core/bitstreams/"
            "020cac11-563b-42d1-b12d-ac4604369797/content"
        ),
        landing_page="https://iris.who.int/handle/10665/325131",
        license_note="CC BY-NC-SA 3.0 IGO; non-commercial use with attribution.",
    ),
    ExternalDocument(
        filename="nih_manual_of_operations_guidelines.pdf",
        title="Guidelines for Developing a Manual of Operations and Procedures",
        publisher="NIH National Center for Complementary and Integrative Health",
        url=("https://files.nccih.nih.gov/s3fs-public/CR-Toolbox/MOP_NCCIH_ver1_07-17-2015.pdf"),
        landing_page="https://www.nccih.nih.gov/grants/toolbox",
        license_note=(
            "Official U.S. Government resource. Stored locally for demonstration; "
            "verify any third-party content notices before redistribution."
        ),
    ),
)


def _download(client: httpx.Client, item: ExternalDocument, output_dir: Path) -> Path:
    destination = output_dir / item.filename
    temporary = destination.with_suffix(".download")
    size = 0
    prefix = bytearray()
    with client.stream("GET", item.url) as response:
        response.raise_for_status()
        with temporary.open("wb") as output:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError(f"{item.title} exceeds the {MAX_BYTES} byte limit.")
                if len(prefix) < 1024:
                    prefix.extend(chunk[: 1024 - len(prefix)])
                output.write(chunk)
    if b"%PDF-" not in prefix:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"{item.title} did not return a PDF.")
    temporary.replace(destination)
    return destination


def main() -> None:
    output_dir = PROJECT_ROOT / ".data" / "demo_documents"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0),
        headers={"User-Agent": "medical-document-assistant-demo-fetcher/0.1"},
    ) as client:
        for item in DOCUMENTS:
            path = _download(client, item, output_dir)
            record = asdict(item)
            record["local_path"] = str(path.relative_to(PROJECT_ROOT))
            record["size_bytes"] = path.stat().st_size
            manifest.append(record)
            print(f"Downloaded {item.title} -> {record['local_path']}")

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
