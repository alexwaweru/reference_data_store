"""
Fields of Study reference-data builder.

Produces a two-level hierarchy of academic fields aligned to the UNESCO/Eurostat
ISCED-F 2013 standard (International Standard Classification of Education —
Fields of Education and Training 2013).

Source:
    https://www.uis.unesco.org/sites/default/files/medias/fichiers/2025/04/
    international-standard-classification-of-education-fields-of-education-and-
    training-2013-detailed-field-descriptions-2015-en.pdf

Outputs (./outputs/):
    fields_of_study.json — 40 records (11 broad fields + 29 narrow fields)

Hierarchy:
    broad  — 2-digit codes  (e.g. "04" Business, administration and law)
    narrow — 3-digit codes  (e.g. "041" Business and administration)

The same shape (`code`, `name`, `level`, `parent_code`) is used at both levels
so a single reader / seeder handles the whole file.

Usage:
    python fields_of_study/build.py
    python fields_of_study/build.py --force    # rebuild even if output exists
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("fields_of_study.build")

ROOT = Path(__file__).parent
OUTPUTS = ROOT / "outputs"

# ── ISCED-F 2013 broad fields (11 fields, 2-digit codes) ──────────────────────
BROAD_FIELDS: list[dict[str, Any]] = [
    {"code": "00", "name": "Generic programmes and qualifications", "level": "broad", "parent_code": None},
    {"code": "01", "name": "Education", "level": "broad", "parent_code": None},
    {"code": "02", "name": "Arts and humanities", "level": "broad", "parent_code": None},
    {"code": "03", "name": "Social sciences, journalism and information", "level": "broad", "parent_code": None},
    {"code": "04", "name": "Business, administration and law", "level": "broad", "parent_code": None},
    {"code": "05", "name": "Natural sciences, mathematics and statistics", "level": "broad", "parent_code": None},
    {"code": "06", "name": "Information and communication technologies", "level": "broad", "parent_code": None},
    {"code": "07", "name": "Engineering, manufacturing and construction", "level": "broad", "parent_code": None},
    {"code": "08", "name": "Agriculture, forestry, fisheries and veterinary", "level": "broad", "parent_code": None},
    {"code": "09", "name": "Health and welfare", "level": "broad", "parent_code": None},
    {"code": "10", "name": "Services", "level": "broad", "parent_code": None},
]

# ── ISCED-F 2013 narrow fields (29 fields, 3-digit codes) ─────────────────────
NARROW_FIELDS: list[dict[str, Any]] = [
    # 00 Generic programmes and qualifications
    {"code": "001", "name": "Basic programmes and qualifications", "level": "narrow", "parent_code": "00"},
    {"code": "002", "name": "Literacy and numeracy", "level": "narrow", "parent_code": "00"},
    {"code": "003", "name": "Personal skills and development", "level": "narrow", "parent_code": "00"},
    # 01 Education
    {"code": "011", "name": "Education", "level": "narrow", "parent_code": "01"},
    # 02 Arts and humanities
    {"code": "021", "name": "Arts", "level": "narrow", "parent_code": "02"},
    {"code": "022", "name": "Humanities (except languages)", "level": "narrow", "parent_code": "02"},
    {"code": "023", "name": "Languages", "level": "narrow", "parent_code": "02"},
    # 03 Social sciences, journalism and information
    {"code": "031", "name": "Social and behavioural sciences", "level": "narrow", "parent_code": "03"},
    {"code": "032", "name": "Journalism and information", "level": "narrow", "parent_code": "03"},
    # 04 Business, administration and law
    {"code": "041", "name": "Business and administration", "level": "narrow", "parent_code": "04"},
    {"code": "042", "name": "Law", "level": "narrow", "parent_code": "04"},
    # 05 Natural sciences, mathematics and statistics
    {"code": "051", "name": "Biological and related sciences", "level": "narrow", "parent_code": "05"},
    {"code": "052", "name": "Environment", "level": "narrow", "parent_code": "05"},
    {"code": "053", "name": "Physical sciences", "level": "narrow", "parent_code": "05"},
    {"code": "054", "name": "Mathematics and statistics", "level": "narrow", "parent_code": "05"},
    # 06 Information and communication technologies
    {"code": "061", "name": "Information and communication technologies", "level": "narrow", "parent_code": "06"},
    # 07 Engineering, manufacturing and construction
    {"code": "071", "name": "Engineering and engineering trades", "level": "narrow", "parent_code": "07"},
    {"code": "072", "name": "Manufacturing and processing", "level": "narrow", "parent_code": "07"},
    {"code": "073", "name": "Architecture and construction", "level": "narrow", "parent_code": "07"},
    # 08 Agriculture, forestry, fisheries and veterinary
    {"code": "081", "name": "Agriculture", "level": "narrow", "parent_code": "08"},
    {"code": "082", "name": "Forestry", "level": "narrow", "parent_code": "08"},
    {"code": "083", "name": "Fisheries", "level": "narrow", "parent_code": "08"},
    {"code": "084", "name": "Veterinary", "level": "narrow", "parent_code": "08"},
    # 09 Health and welfare
    {"code": "091", "name": "Health", "level": "narrow", "parent_code": "09"},
    {"code": "092", "name": "Welfare", "level": "narrow", "parent_code": "09"},
    # 10 Services
    {"code": "101", "name": "Personal services", "level": "narrow", "parent_code": "10"},
    {"code": "102", "name": "Hygiene and occupational health services", "level": "narrow", "parent_code": "10"},
    {"code": "103", "name": "Security services", "level": "narrow", "parent_code": "10"},
    {"code": "104", "name": "Transport services", "level": "narrow", "parent_code": "10"},
    {"code": "108", "name": "Interdisciplinary programmes and qualifications involving services", "level": "narrow", "parent_code": "10"},
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
    out = OUTPUTS / "fields_of_study.json"
    if not should_build(out, force):
        return
    records = BROAD_FIELDS + NARROW_FIELDS
    write_json(out, records)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build ISCED-F 2013 fields of study reference data."
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
