"""
Location reference-data fetcher.

Downloads JSON files from alexwaweru/countries-states-cities-database, normalizes
the shape into something stable, and writes them to ./outputs/ for any downstream
consumer (Prisma, Drizzle, SQLAlchemy, …) to seed.

Source:
    https://github.com/alexwaweru/countries-states-cities-database

Outputs (./outputs/):
    regions.json       — ~6 rows  (continents)
    subregions.json    — ~22 rows
    countries.json     — 250 rows
    states.json        — ~5,000 rows (states / provinces / regions)
    cities.json        — ~150,000 rows

Usage:
    python locations/fetch.py                    # fetches everything including cities
    python locations/fetch.py --only countries
    python locations/fetch.py --force            # re-fetch even if outputs exist

Why we normalize here instead of seeding directly:
    The output JSON is the contract between this repo and the application.
    Any language can read JSON; seeding logic is a 30-line loop in any ORM.
    Decoupling fetch+normalize from seed means a Prisma project, a Django
    project, and a Drizzle project can all share the same artifacts.
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

logger = logging.getLogger("locations.fetch")

ROOT = Path(__file__).parent
OUTPUTS = ROOT / "outputs"

BASE_URL = "https://raw.githubusercontent.com/alexwaweru/countries-states-cities-database/master/json"

# Map of step → (remote filename, output filename). Order matters: regions
# must be fetched before countries so the region-name → id lookup is available.
STEPS = (
    ("regions", "regions.json"),
    ("subregions", "subregions.json"),
    ("countries", "countries.json"),
    ("states", "states.json"),
    ("cities", "cities.json"),
)
STEP_NAMES = tuple(s for s, _ in STEPS)

MAX_RETRIES = 3
RETRY_DELAY_S = 5
FETCH_TIMEOUT_S = 600  # cities.json is large


def fetch_json(filename: str) -> Any:
    url = f"{BASE_URL}/{filename}"
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


def normalize_region(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "translations": r.get("translations") or {},
        "wikidata_id": r.get("wikiDataId"),
    }


def normalize_subregion(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": s["id"],
        "name": s["name"],
        "region_id": s.get("region_id"),
        "translations": s.get("translations") or {},
        "wikidata_id": s.get("wikiDataId"),
    }


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_country(
    c: dict[str, Any],
    region_name_to_id: dict[str, int],
    subregion_name_to_id: dict[str, int],
) -> dict[str, Any]:
    # The current dr5hn release stores region/subregion as string names.
    # Resolve to ids so consumers can use stable FK columns.
    region_name = c.get("region")
    subregion_name = c.get("subregion")
    return {
        "id": c["id"],
        "name": c["name"],
        "iso2": c.get("iso2"),
        "iso3": c.get("iso3"),
        "numeric_code": c.get("numeric_code"),
        "phonecode": c.get("phonecode"),
        "capital": c.get("capital"),
        "currency": c.get("currency"),
        "currency_name": c.get("currency_name"),
        "currency_symbol": c.get("currency_symbol"),
        "tld": c.get("tld"),
        "native": c.get("native"),
        "region_id": region_name_to_id.get(region_name) if region_name else None,
        "subregion_id": subregion_name_to_id.get(subregion_name) if subregion_name else None,
        "nationality": c.get("nationality"),
        "timezones": c.get("timezones") or [],
        "translations": c.get("translations") or {},
        "latitude": _float_or_none(c.get("latitude")),
        "longitude": _float_or_none(c.get("longitude")),
        "emoji": c.get("emoji"),
        "emoji_u": c.get("emojiU"),
        "wikidata_id": c.get("wikiDataId"),
        "population": c.get("population"),
        "gdp": c.get("gdp"),
        "area_sq_km": c.get("area_sq_km"),
        "postal_code_format": c.get("postal_code_format"),
        "postal_code_regex": c.get("postal_code_regex"),
    }


def normalize_state(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": s["id"],
        "name": s["name"],
        "country_id": s.get("country_id"),
        "country_code": s.get("country_code"),
        "fips_code": s.get("fips_code"),
        "iso2": s.get("iso2"),
        "iso3166_2": s.get("iso3166_2"),
        "state_code": s.get("state_code") or s.get("iso2") or "",
        "type": s.get("type"),
        "level": s.get("level"),
        "parent_id": s.get("parent_id"),
        "native": s.get("native"),
        "latitude": _float_or_none(s.get("latitude")),
        "longitude": _float_or_none(s.get("longitude")),
        "timezone": s.get("timezone"),
        "translations": s.get("translations") or {},
        "wikidata_id": s.get("wikiDataId"),
        "population": s.get("population"),
    }


def normalize_city(
    c: dict[str, Any],
    state_id: int,
    state_code: str,
    country_id: int,
    country_code: str,
) -> dict[str, Any] | None:
    """Cities without coordinates are dropped — they're useless for geo queries."""
    lat = _float_or_none(c.get("latitude"))
    lon = _float_or_none(c.get("longitude"))
    if lat is None or lon is None:
        return None
    return {
        "id": c["id"],
        "name": c["name"],
        "state_id": state_id,
        "state_code": state_code,
        "country_id": country_id,
        "country_code": country_code,
        "latitude": lat,
        "longitude": lon,
        "type": c.get("type"),
        "level": c.get("level"),
        "parent_id": c.get("parent_id"),
        "native": c.get("native"),
        "population": c.get("population"),
        "timezone": c.get("timezone"),
        "translations": c.get("translations") or {},
        "wikidata_id": c.get("wikiDataId"),
    }


def should_build(path: Path, force: bool) -> bool:
    if force:
        return True
    if path.exists():
        logger.info("Skipping %s (already exists; pass --force to rebuild)", path.name)
        return False
    return True


def run(steps: set[str], force: bool) -> None:
    region_name_to_id: dict[str, int] = {}
    subregion_name_to_id: dict[str, int] = {}

    if "regions" in steps:
        out = OUTPUTS / "regions.json"
        if should_build(out, force):
            data = [normalize_region(r) for r in fetch_json("regions.json")]
            write_json(out, data)
        else:
            data = json.loads(out.read_text(encoding="utf-8"))
        region_name_to_id = {r["name"]: r["id"] for r in data}

    if "subregions" in steps:
        out = OUTPUTS / "subregions.json"
        if should_build(out, force):
            data = [normalize_subregion(s) for s in fetch_json("subregions.json")]
            write_json(out, data)
        else:
            data = json.loads(out.read_text(encoding="utf-8"))
        subregion_name_to_id = {s["name"]: s["id"] for s in data}

    if "countries" in steps and should_build(OUTPUTS / "countries.json", force):
        # If the user ran --only countries we still need the lookups.
        if not region_name_to_id:
            try:
                regions = json.loads((OUTPUTS / "regions.json").read_text(encoding="utf-8"))
                region_name_to_id = {r["name"]: r["id"] for r in regions}
            except FileNotFoundError:
                regions = [normalize_region(r) for r in fetch_json("regions.json")]
                region_name_to_id = {r["name"]: r["id"] for r in regions}
        if not subregion_name_to_id:
            try:
                subs = json.loads((OUTPUTS / "subregions.json").read_text(encoding="utf-8"))
                subregion_name_to_id = {s["name"]: s["id"] for s in subs}
            except FileNotFoundError:
                subs = [normalize_subregion(s) for s in fetch_json("subregions.json")]
                subregion_name_to_id = {s["name"]: s["id"] for s in subs}

        countries = [
            normalize_country(c, region_name_to_id, subregion_name_to_id)
            for c in fetch_json("countries.json")
        ]
        write_json(OUTPUTS / "countries.json", countries)

    if "states" in steps and should_build(OUTPUTS / "states.json", force):
        states = [normalize_state(s) for s in fetch_json("states.json")]
        write_json(OUTPUTS / "states.json", states)

    if "cities" in steps and should_build(OUTPUTS / "cities.json", force):
        # Cities are nested inside countries+states+cities.json: country → state → city[]
        raw_countries = fetch_json("countries+states+cities.json")
        cities: list[dict[str, Any]] = []
        skipped = 0
        for country in raw_countries:
            for state in country.get("states") or []:
                s_code = state.get("state_code") or state.get("iso2") or ""
                for c in state.get("cities") or []:
                    normalized = normalize_city(c, state["id"], s_code, country["id"], country["iso2"])
                    if normalized is None:
                        skipped += 1
                        continue
                    cities.append(normalized)
        logger.info("Cities: %d kept, %d skipped (missing coords)", len(cities), skipped)
        write_json(OUTPUTS / "cities.json", cities)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch + normalize location reference data.")
    parser.add_argument(
        "--only",
        choices=STEP_NAMES,
        action="append",
        help="Run only the given step(s). May be passed multiple times. Default: everything except cities.",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild outputs even if they exist.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)

    if args.only:
        steps = set(args.only)
    else:
        steps = set(STEP_NAMES)

    run(steps=steps, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
