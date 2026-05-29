"""
Qualifications reference-data builder.

Produces a predefined list of education qualification levels aligned to the
UNESCO ISCED 2011 standard (International Standard Classification of Education).

Source:
    https://isced.uis.unesco.org/  (ISCED 2011)

Output (./outputs/):
    qualifications.json — 8 qualification levels (ISCED 1-8)

Each record maps a practical job-platform label (e.g. "A levels", "Postgraduate")
to its canonical ISCED level and name so consumers can filter or display either.
ISCED 0 (early childhood) is excluded — not relevant for employment contexts.

Usage:
    python qualifications/build.py
    python qualifications/build.py --force    # rebuild even if output exists
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("qualifications.build")

ROOT = Path(__file__).parent
OUTPUTS = ROOT / "outputs"

# ISCED 2011 levels, augmented with practical labels used on job platforms.
# label      — short display string for UIs and dropdowns
# examples   — illustrative qualifications from different regional systems
QUALIFICATIONS: list[dict[str, Any]] = [
    {
        "id": 1,
        "isced_level": 1,
        "code": "ISCED-1",
        "name": "Primary education",
        "label": "Primary school certificate",
        "examples": ["Primary school leaving certificate", "FSLC"],
    },
    {
        "id": 2,
        "isced_level": 2,
        "code": "ISCED-2",
        "name": "Lower secondary education",
        "label": "O levels / Junior Certificate",
        "examples": ["O levels", "GCSE", "BECE", "BEPC", "Junior Certificate"],
    },
    {
        "id": 3,
        "isced_level": 3,
        "code": "ISCED-3",
        "name": "Upper secondary education",
        "label": "A levels / Senior Certificate",
        "examples": ["A levels", "WASSCE", "Baccalauréat", "Matura", "Senior Certificate"],
    },
    {
        "id": 4,
        "isced_level": 4,
        "code": "ISCED-4",
        "name": "Post-secondary non-tertiary education",
        "label": "Technical / Vocational certificate",
        "examples": [
            "National Vocational Certificate",
            "City & Guilds",
            "Technical certificate",
            "Vocational diploma",
        ],
    },
    {
        "id": 5,
        "isced_level": 5,
        "code": "ISCED-5",
        "name": "Short-cycle tertiary education",
        "label": "Associate degree / HND",
        "examples": ["Associate degree", "HND", "Foundation degree", "DUT"],
    },
    {
        "id": 6,
        "isced_level": 6,
        "code": "ISCED-6",
        "name": "Bachelor's or equivalent level",
        "label": "Bachelor's degree / Graduate",
        "examples": ["BSc", "BA", "BEng", "LLB", "BTech"],
    },
    {
        "id": 7,
        "isced_level": 7,
        "code": "ISCED-7",
        "name": "Master's or equivalent level",
        "label": "Master's degree / Postgraduate",
        "examples": ["MSc", "MA", "MBA", "MEng", "LLM", "Postgraduate diploma"],
    },
    {
        "id": 8,
        "isced_level": 8,
        "code": "ISCED-8",
        "name": "Doctoral or equivalent level",
        "label": "PhD / Doctorate",
        "examples": ["PhD", "DPhil", "EdD", "MD (research)", "Professional doctorate"],
    },
]


def write_json(path: Path, payload: Any) -> None:
    logger.info("Writing %s (%d records)", path.name, len(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def should_build(path: Path, force: bool) -> bool:
    if force:
        return True
    if path.exists():
        logger.info("Skipping %s (already exists; pass --force to rebuild)", path.name)
        return False
    return True


def run(force: bool) -> None:
    out = OUTPUTS / "qualifications.json"
    if not should_build(out, force):
        return
    write_json(out, QUALIFICATIONS)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build ISCED 2011 qualifications reference data."
    )
    parser.add_argument("--force", action="store_true", help="Rebuild output even if it exists.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    run(force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
