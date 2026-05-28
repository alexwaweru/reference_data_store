"""
Inflate the .gz artifacts that ship in this repo so the uncompressed JSON /
NPY is available locally.

Run this once after `git clone`. It walks the repo, finds every `*.gz`, and
writes the decompressed sibling next to it (only if the sibling is missing
or out-of-date).

Usage:
    python tools/decompress.py                # decompress everything
    python tools/decompress.py --force        # overwrite even if up to date
    python tools/decompress.py --dry-run

Consumers who'd rather read `.json.gz` directly from their seeder (every
modern language has a one-liner for this) can skip this step — see the
top-level README for snippets.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger("tools.decompress")

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {".git", ".venv", ".cache", "__pycache__", "node_modules"}


def iter_archives(root: Path) -> list[Path]:
    archives: list[Path] = []
    for path in root.rglob("*.gz"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        archives.append(path)
    return archives


def is_up_to_date(gz_path: Path, dest: Path) -> bool:
    return dest.exists() and dest.stat().st_mtime >= gz_path.stat().st_mtime


def decompress(gz_path: Path) -> Path:
    """Write the inflated file next to <gz_path> (strips the .gz suffix)."""
    dest = gz_path.with_suffix("")  # strips ".gz"
    with gzip.open(gz_path, "rb") as src, dest.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    return dest


def run(force: bool, dry_run: bool) -> None:
    archives = iter_archives(ROOT)
    if not archives:
        logger.info("No .gz files found under %s", ROOT)
        return

    done = 0
    for gz_path in sorted(archives):
        rel = gz_path.relative_to(ROOT)
        dest = gz_path.with_suffix("")
        if not force and is_up_to_date(gz_path, dest):
            logger.info("Up to date: %s (pass --force to re-extract)", rel)
            continue
        if dry_run:
            logger.info("Would extract %s → %s", rel, dest.relative_to(ROOT))
            done += 1
            continue
        decompress(gz_path)
        logger.info(
            "Extracted %s (%.1f MB → %.1f MB)",
            rel,
            gz_path.stat().st_size / 1024 / 1024,
            dest.stat().st_size / 1024 / 1024,
        )
        done += 1

    logger.info("%d archive(s) processed.", done)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inflate gzipped JSON / NPY artifacts.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if the destination is newer than the archive.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what would be done without writing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    run(force=args.force, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
