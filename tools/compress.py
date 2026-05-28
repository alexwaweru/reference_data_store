"""
Compress large generated JSON / NPY files so they fit under GitHub's 100MB
file size limit.

Walks the repo, finds files matching the configured extensions whose size
exceeds the threshold, and writes a sibling `<file>.gz` using gzip -9. The
original is kept on disk (gitignored) so build/fetch scripts can keep
reading it directly during development.

Usage:
    python tools/compress.py                      # default: 50 MB threshold
    python tools/compress.py --threshold 90       # only compress files > 90 MB
    python tools/compress.py --dry-run            # show what would be compressed

Run this whenever you regenerate the large outputs (typically after
`python esco_taxonomy/build.py --force`) so the committed `.gz` artifacts
stay in sync with the underlying data.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger("tools.compress")

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = (".json", ".npy")
EXCLUDE_DIRS = {".git", ".venv", ".cache", "__pycache__", "node_modules"}


def iter_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix not in EXTENSIONS:
            continue
        candidates.append(path)
    return candidates


def compress(path: Path) -> int:
    """Write <path>.gz next to <path>. Returns the compressed size in bytes."""
    gz_path = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    return gz_path.stat().st_size


def run(threshold_bytes: int, dry_run: bool) -> None:
    candidates = iter_candidates(ROOT)
    compressed = 0
    for path in sorted(candidates):
        size = path.stat().st_size
        if size < threshold_bytes:
            continue
        rel = path.relative_to(ROOT)
        if dry_run:
            logger.info("Would compress %s (%.1f MB)", rel, size / 1024 / 1024)
            compressed += 1
            continue

        gz_size = compress(path)
        ratio = size / gz_size if gz_size else 1.0
        logger.info(
            "Compressed %s: %.1f MB → %.1f MB (%.1fx)",
            rel,
            size / 1024 / 1024,
            gz_size / 1024 / 1024,
            ratio,
        )
        compressed += 1

    if compressed == 0:
        logger.info("Nothing to compress (no files above %.0f MB threshold).", threshold_bytes / 1024 / 1024)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gzip large JSON / NPY files for git-friendliness.")
    parser.add_argument(
        "--threshold",
        type=int,
        default=50,
        help="Compress files larger than this many MB (default: 50). GitHub's hard limit is 100.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what would be done without writing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    run(threshold_bytes=args.threshold * 1024 * 1024, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
