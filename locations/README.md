# Locations

Country / state / city reference data sourced from
[dr5hn/countries-states-cities-database](https://github.com/dr5hn/countries-states-cities-database).
Used for address selection, geo-filtering, distance queries, and any place a
canonical country / state / city ID is needed.

This folder follows the same contract as the rest of the repo:
**Python is only used here for scripting.** The outputs are pure JSON and are
meant to be consumed from any language / framework (Prisma, Drizzle,
SQLAlchemy, Django, Hibernate, …).

---

## How to fetch

```bash
python locations/fetch.py                       # regions + subregions + countries + states
python locations/fetch.py --include-cities      # adds cities.json (~150k rows, slow)
python locations/fetch.py --only countries      # one specific layer
python locations/fetch.py --force               # re-fetch even if outputs exist
```

The script normalizes the upstream JSON: it resolves region/subregion name
references into stable IDs, coerces lat/lng to floats, drops cities without
coordinates (they're useless for geo queries), and writes one file per layer
under `outputs/`.

---

## Outputs (the contract — these are what you seed)

| File | Rows | Purpose |
|---|---|---|
| `outputs/regions.json` | 6 | Continents — Africa, Americas, Asia, Europe, Oceania, Polar |
| `outputs/subregions.json` | 22 | UN sub-regions — Western Europe, South-Eastern Asia, etc. |
| `outputs/countries.json` | 250 | ISO 3166-1 countries with currency, phone code, ISO codes, lat/lng, flag emoji |
| `outputs/states.json` | ~5,300 | First-order administrative divisions — states, provinces, regions |
| `outputs/cities.json` | ~150,000 | Cities with lat/lng (only fetched with `--include-cities`) |

### Record shapes

`countries.json`:
```json
{
  "id": 1,
  "name": "Afghanistan",
  "iso2": "AF",
  "iso3": "AFG",
  "numeric_code": "004",
  "phonecode": "93",
  "capital": "Kabul",
  "currency": "AFN",
  "currency_name": "Afghan afghani",
  "currency_symbol": "؋",
  "tld": ".af",
  "native": "افغانستان",
  "region_id": 3,
  "subregion_id": 14,
  "nationality": "Afghan",
  "timezones": [{ "zoneName": "Asia/Kabul", "gmtOffset": 16200, ... }],
  "translations": { "kr": "아프가니스탄", ... },
  "latitude": 33.0,
  "longitude": 65.0,
  "emoji": "🇦🇫",
  "emoji_u": "U+1F1E6 U+1F1EB",
  "wikidata_id": "Q889",
  "population": 38928346,
  "gdp": 19101000000,
  "area_sq_km": 652230
}
```

`states.json` / `cities.json` shape: see `fetch.py:normalize_state` /
`normalize_city` — `latitude` and `longitude` are floats (or null for states
without coords); cities without coords are dropped.

---

## Recommended database schema

Five tables, one per JSON file. **Use PostGIS** for the geo columns — point
storage + GIS indexing is what makes "find users within X km" and "sort by
distance" tractable.

| Table | Columns |
|---|---|
| `location_region` | `id` PK, `name`, `translations` JSONB, `wikidata_id` |
| `location_subregion` | `id` PK, `name`, `region_id` FK, `translations` JSONB, `wikidata_id` |
| `location_country` | `id` PK, `name`, `iso2` UNIQUE, `iso3` UNIQUE, `numeric_code`, `phonecode`, `capital`, `currency`, `currency_name`, `currency_symbol`, `tld`, `native`, `region_id` FK, `subregion_id` FK, `nationality`, `timezones` JSONB, `translations` JSONB, **`location` GEOGRAPHY(Point, 4326)**, `emoji`, `emoji_u`, `wikidata_id`, `population` BIGINT, `gdp` BIGINT, `area_sq_km` INT, `postal_code_format`, `postal_code_regex` |
| `location_state` | `id` PK, `name`, `country_id` FK, `country_code`, `fips_code`, `iso2`, `iso3166_2`, `state_code`, `state_type`, `level` INT, `parent_id` FK (self), `native`, **`location` GEOGRAPHY(Point, 4326)**, `timezone`, `translations` JSONB, `wikidata_id`, `population` BIGINT |
| `location_city` | `id` PK, `name`, `state_id` FK, `state_code`, `country_id` FK, `country_code`, **`location` GEOGRAPHY(Point, 4326) NOT NULL**, `city_type`, `level` INT, `parent_id` FK (self), `native`, `population` BIGINT, `timezone`, `translations` JSONB, `wikidata_id` |

### Why `GEOGRAPHY(Point, 4326)` instead of two `float` columns

- It stores lng/lat as a single value indexable with GiST — distance queries
  use a real spatial index instead of full-table scans.
- It uses the geodetic model, so `ST_Distance(a, b)` returns meters on a
  sphere — no need to remember Haversine or convert degrees to km.
- Common queries become one-liners:
  ```sql
  -- Cities within 50 km of a point, ordered by distance:
  SELECT name, ST_Distance(location, ST_MakePoint($lng, $lat)::geography) AS meters
  FROM   location_city
  WHERE  ST_DWithin(location, ST_MakePoint($lng, $lat)::geography, 50000)
  ORDER  BY location <-> ST_MakePoint($lng, $lat)::geography
  LIMIT  20;
  ```

If your DB doesn't support PostGIS (SQLite, MySQL without GIS, etc.), store
`latitude` and `longitude` as separate `DOUBLE PRECISION` columns and filter
with a Haversine UDF — accept that you'll lose the spatial index.

### Self-referential `parent_id` on states and cities

Some upstream rows reference a parent in the same table (e.g. a county nested
under a state). The seeder must do this in **two passes**: insert all rows with
`parent_id = NULL` first, then `UPDATE … SET parent_id = …` once the referenced
IDs are guaranteed to exist. The lookup loop in `fetch.py` already collects
the (id, parent_id) pairs; mirror it in your seeder.

---

## Seeding patterns (framework-agnostic)

The shape is the same in every ORM:

```text
load JSON file
in batches of 500-1000:
    INSERT INTO <table> (...) VALUES (...)
    ON CONFLICT (id) DO UPDATE SET <columns> = EXCLUDED.<column>, updated_at = NOW()
```

Order matters: regions → subregions → countries → states → cities. Each layer
references the previous one by ID.

When writing the `location` column, convert lat/lng to PostGIS at insert time:

```sql
ST_SetSRID(ST_MakePoint($longitude::float8, $latitude::float8), 4326)::geography
```

Note the argument order — **longitude first**, then latitude.

### Prisma (TypeScript)

```ts
import { Prisma } from '@prisma/client'

await prisma.$executeRaw`
  INSERT INTO location_country (id, name, iso2, iso3, location, ...)
  VALUES (
    ${c.id}, ${c.name}, ${c.iso2}, ${c.iso3},
    ${c.latitude != null && c.longitude != null
      ? Prisma.sql`ST_SetSRID(ST_MakePoint(${c.longitude}::float8, ${c.latitude}::float8), 4326)::geography`
      : Prisma.sql`NULL::geography`},
    ...
  )
  ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, iso2 = EXCLUDED.iso2, ...
`
```

A full worked example lives at
`apps/api/prisma/seed-locations.ts` in the Liberia Works backend — same data,
same pattern.

### Django + GeoDjango

```python
from django.contrib.gis.geos import Point

country.location = Point(c['longitude'], c['latitude'])  # lng, lat
country.save()
```

### SQLAlchemy + GeoAlchemy2

```python
from geoalchemy2.elements import WKTElement

country.location = WKTElement(f'POINT({c["longitude"]} {c["latitude"]})', srid=4326)
```

### Drizzle (TypeScript)

Drizzle has no native PostGIS column type — declare it as a custom type or use
raw SQL (`sql\`ST_MakePoint(${lng}, ${lat})\``) on insert. Same pattern as
Prisma above.

---

## Common queries

Find country by ISO2:

```sql
SELECT * FROM location_country WHERE iso2 = 'US';
```

Cities in a country, ordered by population:

```sql
SELECT c.name, c.population, s.name AS state
FROM   location_city c JOIN location_state s ON s.id = c.state_id
WHERE  c.country_code = 'US'
ORDER  BY c.population DESC NULLS LAST
LIMIT  100;
```

Nearest city to a coordinate (PostGIS only):

```sql
SELECT id, name,
       ST_Distance(location, ST_MakePoint($lng, $lat)::geography) / 1000 AS km
FROM   location_city
ORDER  BY location <-> ST_MakePoint($lng, $lat)::geography
LIMIT  1;
```

---

## Refresh cadence

The upstream dataset is updated monthly-ish. Re-run `python locations/fetch.py
--force` on demand. The `ON CONFLICT … DO UPDATE` pattern in your seeder makes
re-running safe.
