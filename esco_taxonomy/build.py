"""
ESCO preprocessing pipeline.

Takes the raw ESCO exports (occupation index, skills index, occupation→skill
relations, and the precomputed embedding .npy files) and produces three JSON
artifacts that are ready to be seeded into the application database — the
output is framework-agnostic, you bring your own ORM (Prisma, SQLAlchemy,
Django, Drizzle, etc.):

  - nested_occupations_skills.json
      Each occupation enriched with its essential/optional skill links. Use
      this to populate the occupation table AND the occupation↔skill edge
      table in one pass.

  - occupations_embeddings.json
      Each occupation augmented with its embedding vector. Load straight into
      whatever vector column / index your DB supports (pgvector, etc.).

  - skills_embeddings.json
      Same shape as above, for skills.

Embeddings are generated ONCE upstream (the .npy files) and persisted into
these JSON artifacts, then loaded into the DB at seed time. The runtime
matching path (job seeker ↔ occupation/skill) only embeds the *incoming query*
— it never re-embeds the catalogue, so we avoid paying for an LLM/embedding
API call per match.

The script is idempotent: existing output files are skipped unless --force is
passed. Embeddings and index files must be aligned row-by-row (this is the
contract guaranteed by the upstream embedding step).

Usage:
    python esco_taxonomy/build.py                       # build any missing outputs
    python esco_taxonomy/build.py --force               # rebuild all outputs
    python esco_taxonomy/build.py --only nested         # build only nested_occupations_skills.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np

# Files this size or larger get a .gz sibling at write time so they fit under
# GitHub's 100 MB per-file limit. Reads transparently handle both formats.
LARGE_FILE_THRESHOLD_BYTES = 50 * 1024 * 1024

logger = logging.getLogger("esco.preprocess")

ROOT = Path(__file__).parent
INPUTS = ROOT / "inputs"
OUTPUTS = ROOT / "outputs"

# Inputs
OCCUP_SKILLS_FILE = INPUTS / "ESCO_occup_skills.json"
SKILLS_INDEX_FILE = INPUTS / "esco_skills_index.json"
OCCUPATIONS_INDEX_FILE = INPUTS / "esco_occupation_index.json"
OCCUPATIONS_EMBEDDINGS_FILE = INPUTS / "occupations_en.embeddings-256.npy"
SKILLS_EMBEDDINGS_FILE = INPUTS / "skills_en.embeddings-256.npy"

# Outputs
NESTED_OUTPUT_FILE = OUTPUTS / "nested_occupations_skills.json"
OCCUPATIONS_EMBEDDINGS_OUTPUT_FILE = OUTPUTS / "occupations_embeddings.json"
SKILLS_EMBEDDINGS_OUTPUT_FILE = OUTPUTS / "skills_embeddings.json"

STEPS = ("nested", "occupations", "skills")


def load_json(path: Path) -> Any:
    """
    Read JSON from `path`, transparently falling back to `<path>.gz`.

    A fresh clone will have the large inputs / outputs only as .gz (the
    uncompressed versions are gitignored). Build steps don't care which is
    present.
    """
    gz_path = path.with_suffix(path.suffix + ".gz")
    if path.exists():
        logger.info("Reading %s", path.name)
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    if gz_path.exists():
        logger.info("Reading %s (gzipped)", gz_path.name)
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(f"Neither {path} nor {gz_path} exists")


def write_json(path: Path, payload: Any) -> None:
    """
    Write JSON to `path`. If the file ends up larger than
    LARGE_FILE_THRESHOLD_BYTES, also write `<path>.gz` so it can be committed
    in place of the (gitignored) uncompressed version. A stale .gz is
    deleted when the file shrinks back below the threshold.
    """
    logger.info("Writing %s (%d records)", path.name, len(payload))
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    gz_path = path.with_suffix(path.suffix + ".gz")
    size = path.stat().st_size
    if size >= LARGE_FILE_THRESHOLD_BYTES:
        with path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        logger.info(
            "Also wrote %s (%.1f MB → %.1f MB)",
            gz_path.name,
            size / 1024 / 1024,
            gz_path.stat().st_size / 1024 / 1024,
        )
    elif gz_path.exists():
        gz_path.unlink()
        logger.info("Removed stale %s (file is now under the gzip threshold)", gz_path.name)


def build_nested_occupations_skills(
    occupations: list[dict[str, Any]],
    occup_skills: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge each occupation in the index with its essential/optional skill links
    from ESCO_occup_skills.json (keyed by preferredLabel).

    Returns a fresh list so we don't mutate the caller's data.
    """
    nested: list[dict[str, Any]] = []
    missing = 0

    for occupation in occupations:
        label = occupation.get("preferredLabel")
        nested_data = occup_skills.get(label) or {}
        links = nested_data.get("_links") or {}

        if not nested_data:
            missing += 1

        nested.append(
            {
                **occupation,
                "essentialSkills": links.get("hasEssentialSkill", []),
                "optionalSkills": links.get("hasOptionalSkill", []),
            }
        )

    if missing:
        logger.warning("No skill links found for %d / %d occupations", missing, len(occupations))

    return nested


def attach_embeddings(
    items: list[dict[str, Any]],
    embeddings: np.ndarray,
    kind: str,
) -> list[dict[str, Any]]:
    """
    Zip embeddings onto items by row index. The upstream embedding pipeline
    guarantees row-aligned ordering — assert it here so we fail loudly if that
    invariant ever breaks.
    """
    if len(items) != len(embeddings):
        raise ValueError(
            f"{kind}: embedding count ({len(embeddings)}) does not match item count ({len(items)})"
        )

    return [{**item, "embedding": embedding.tolist()} for item, embedding in zip(items, embeddings)]


def should_build(path: Path, force: bool) -> bool:
    if force:
        return True
    if path.exists():
        logger.info("Skipping %s (already exists; pass --force to rebuild)", path.name)
        return False
    return True


def run(steps: set[str], force: bool) -> None:
    if "nested" in steps and should_build(NESTED_OUTPUT_FILE, force):
        occupations = load_json(OCCUPATIONS_INDEX_FILE)
        occup_skills = load_json(OCCUP_SKILLS_FILE)
        write_json(NESTED_OUTPUT_FILE, build_nested_occupations_skills(occupations, occup_skills))

    if "occupations" in steps and should_build(OCCUPATIONS_EMBEDDINGS_OUTPUT_FILE, force):
        occupations = load_json(OCCUPATIONS_INDEX_FILE)
        embeddings = np.load(OCCUPATIONS_EMBEDDINGS_FILE)
        write_json(
            OCCUPATIONS_EMBEDDINGS_OUTPUT_FILE,
            attach_embeddings(occupations, embeddings, kind="occupations"),
        )

    if "skills" in steps and should_build(SKILLS_EMBEDDINGS_OUTPUT_FILE, force):
        skills = load_json(SKILLS_INDEX_FILE)
        embeddings = np.load(SKILLS_EMBEDDINGS_FILE)
        write_json(
            SKILLS_EMBEDDINGS_OUTPUT_FILE,
            attach_embeddings(skills, embeddings, kind="skills"),
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ESCO seed artifacts from raw exports.")
    parser.add_argument(
        "--only",
        choices=STEPS,
        action="append",
        help="Run only the given step(s). May be passed multiple times. Default: run all.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild outputs even if they already exist.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    steps = set(args.only) if args.only else set(STEPS)
    run(steps=steps, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
