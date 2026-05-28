"""
Universities reference-data fetcher.

Downloads Hipo/university-domains-list, normalizes the shape, and writes
universities.json for downstream consumers to seed.

Source:
    https://github.com/Hipo/university-domains-list

Output (./outputs/):
    universities.json — ~10,000 rows

Usage:
    python universities/fetch.py            # fetch if not already present
    python universities/fetch.py --force    # re-fetch

The output is framework-agnostic JSON. See ./README.md for the recommended DB
schema and seed pattern.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("universities.fetch")

ROOT = Path(__file__).parent
OUTPUTS = ROOT / "outputs"

UNIVERSITIES_URL = (
    "https://raw.githubusercontent.com/Hipo/university-domains-list/"
    "refs/heads/master/world_universities_and_domains.json"
)

MAX_RETRIES = 3
RETRY_DELAY_S = 5
FETCH_TIMEOUT_S = 120


def fetch_json(url: str) -> Any:
    logger.info("Fetching %s", url)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as r:  # noqa: S310
                return json.loads(r.read().decode("utf-8"))
        except Exception as err:  # noqa: BLE001
            last_err = err
            if attempt < MAX_RETRIES - 1:
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %ds...",
                    attempt + 1,
                    MAX_RETRIES,
                    err,
                    RETRY_DELAY_S,
                )
                time.sleep(RETRY_DELAY_S)
    raise RuntimeError(f"Failed to fetch {url}") from last_err


def write_json(path: Path, payload: Any) -> None:
    logger.info("Writing %s (%d records)", path.name, len(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def normalize_university(u: dict[str, Any], idx: int) -> dict[str, Any]:
    """
    Hipo's records have no stable ID. We synthesize one from name+country so
    the same row gets the same ID across re-fetches (stable until the upstream
    renames the institution).

    The first domain is treated as the canonical web identity — it's the most
    common joining key in scraping / lookup workflows.
    """
    domains = [d.strip().lower() for d in (u.get("domains") or []) if d]
    web_pages = [w.strip() for w in (u.get("web_pages") or []) if w]
    primary_domain = domains[0] if domains else None

    return {
        # Hipo ships no ID. Use index as a stable-within-this-fetch surrogate;
        # if you need a permanent ID across fetches, key your DB row on
        # (country_code, primary_domain) — both are present below.
        "id": idx,
        "name": u.get("name", "").strip(),
        "country": u.get("country"),
        "country_code": u.get("alpha_two_code"),
        "state_province": u.get("state-province"),
        "primary_domain": primary_domain,
        "domains": domains,
        "web_pages": web_pages,
    }


def should_build(path: Path, force: bool) -> bool:
    if force:
        return True
    if path.exists():
        logger.info("Skipping %s (already exists; pass --force to rebuild)", path.name)
        return False
    return True


def run(force: bool) -> None:
    out = OUTPUTS / "universities.json"
    if not should_build(out, force):
        return

    raw = fetch_json(UNIVERSITIES_URL)
    if not isinstance(raw, list):
        raise ValueError(f"Unexpected response shape: {type(raw).__name__}")

    universities = [normalize_university(u, idx=i + 1) for i, u in enumerate(raw)]
    # Stable ordering: alphabetic by name within country — easier diffs.
    universities.sort(key=lambda u: ((u.get("country_code") or ""), (u.get("name") or "")))
    # Re-number after sort so IDs match output order.
    for i, u in enumerate(universities, start=1):
        u["id"] = i

    write_json(out, universities)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch + normalize universities reference data.")
    parser.add_argument("--force", action="store_true", help="Rebuild outputs even if they exist.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    run(force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
