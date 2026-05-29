# Reference Data Store

A single repo that produces **language- and framework-agnostic JSON** for the
reference datasets a typical job-marketplace / career-platform needs:

- **Locations** — countries, states, cities (with geo coordinates).
- **ESCO taxonomy** — ~3,000 occupations and ~13,000 skills, with embeddings
  for semantic matching.
- **Institutions** — ~10,000 universities worldwide, with their email/web
  domains.
- **Sectors & industries** — the full NAICS 2022 5-level taxonomy.
- **Qualifications** — 8 education levels (ISCED 2011), from primary through
  doctorate, with practical labels like "A levels" and "Postgraduate".
- **Fields of study** — 41 academic fields (ISCED-F 2013): 11 broad fields and
  30 narrow fields, from Arts & Humanities to Engineering & Construction.

Python is used **only for scripting**. Each domain folder has a small Python
script that fetches the upstream source, normalizes the shape, and writes
JSON to `<domain>/outputs/`. Consumers (Prisma, Drizzle, SQLAlchemy, Django,
Hibernate, anything that reads JSON) seed their database from those files.

---

## Folder layout

```
.
├── README.md                              ← you are here
├── pyproject.toml                         ← scripting-time deps only
│
├── tools/
│   ├── compress.py                        ← gzip files > 50 MB to fit GitHub's 100 MB limit
│   └── decompress.py                      ← inflate the *.gz committed to the repo
│
├── locations/
│   ├── README.md                          ← schema + seeding recipes for locations
│   ├── fetch.py                           ← downloads alexwaweru/countries-states-cities-database
│   └── outputs/
│       ├── regions.json                   ← 6 records
│       ├── subregions.json                ← 22 records
│       ├── countries.json                 ← 250 records
│       ├── states.json                    ← ~5,300 records
│       └── cities.json                    ← ~154k records
│
├── esco_taxonomy/
│   ├── README.md                          ← schema, seeding, matching, BYO embeddings
│   ├── build.py                           ← merges raw ESCO + embeddings into seed JSON
│   ├── inputs/                            ← raw ESCO indexes + .npy embedding files
│   └── outputs/
│       ├── occupations_embeddings.json    ← ~3,000 records, each with a 256-d vector
│       ├── skills_embeddings.json         ← ~13,000 records, each with a 256-d vector
│       └── nested_occupations_skills.json ← occupations + their essential/optional skill links
│
├── universities/
│   ├── README.md                          ← schema + student-email verification flow
│   ├── fetch.py                           ← downloads Hipo/university-domains-list
│   └── outputs/
│       └── universities.json              ← ~10,000 records
│
├── sectors/
│   ├── README.md                          ← schema + how to tag companies / jobs
│   ├── fetch.py                           ← downloads NAICS 2022 from census.gov
│   └── outputs/
│       ├── sectors.json                   ← 20 top-level sectors
│       └── industries.json                ← ~2,125 records across all 5 NAICS levels
│
├── qualifications/
│   ├── README.md                          ← schema + seeding + ISCED level map
│   ├── build.py                           ← emits ISCED 2011 levels (hardcoded, no fetch)
│   └── outputs/
│       └── qualifications.json            ← 8 records (ISCED levels 1-8)
│
└── fields_of_study/
    ├── README.md                          ← schema + seeding + full ISCED-F code table
    ├── build.py                           ← emits ISCED-F 2013 fields (hardcoded, no fetch)
    └── outputs/
        └── fields_of_study.json           ← 41 records (11 broad + 30 narrow fields)
```

**The JSON files in each `outputs/` directory are the only contract this repo
exposes.** Everything else (Python, the raw upstream files, the `.cache/`
directories) is implementation detail.

---

## How to run everything

```bash
uv sync                                                  # installs numpy + openpyxl

python tools/decompress.py                               # inflate large .gz artifacts (run once after clone)
python locations/fetch.py                                # ~5-10 min (includes cities)
python esco_taxonomy/build.py                            # ~1 minute (reads inputs/)
python universities/fetch.py                             # ~5s
python sectors/fetch.py                                  # ~5s
python qualifications/build.py                           # instant (hardcoded ISCED 2011)
python fields_of_study/build.py                          # instant (hardcoded ISCED-F 2013)
```

All scripts are idempotent — re-running them is a no-op unless you pass
`--force`. Re-fetching is the right move when the upstream source ships a new
release; the per-folder READMEs document the refresh cadence.

---

## Large files & GitHub's 100 MB limit

Two of the JSON artifacts blow past GitHub's per-file ceiling on their own:

| File | Raw | Gzipped (committed) |
|---|---|---|
| `esco_taxonomy/inputs/ESCO_occup_skills.json` | 164 MB | 15 MB |
| `esco_taxonomy/outputs/skills_embeddings.json` | 104 MB | 35 MB |

The policy: **commit only the `.gz` for files over the threshold; ignore the
uncompressed sibling.** The `.gitignore` already lists the two paths above.
Two small tools handle the round-trip:

```bash
python tools/decompress.py                # run once after clone — inflates every *.gz
python tools/compress.py                  # gzip any file > 50 MB before committing
python tools/compress.py --threshold 90   # tighter threshold (closer to GitHub's hard limit)
python tools/compress.py --dry-run        # see what would be compressed
```

`esco_taxonomy/build.py` is gzip-aware on both sides:

- **Read** — `load_json()` reads `*.json.gz` if the `*.json` is missing, so
  the build runs straight from a fresh clone without inflating anything.
- **Write** — when an output exceeds 50 MB, the script writes both `.json`
  (gitignored) and `.json.gz` (committed) in one pass. A stale `.gz` is
  deleted when the file shrinks back below the threshold.

So the maintainer flow stays simple:

```bash
python esco_taxonomy/build.py --force     # rewrites both .json and .json.gz where applicable
git add esco_taxonomy/outputs/*.json.gz   # only the .gz needs committing
```

### Consuming `.json.gz` directly (no decompress step)

Downstream applications that don't want to inflate to disk can read the
gzipped JSON straight from their seeder. One-liners:

```python
# Python
import gzip, json
with gzip.open("esco_taxonomy/outputs/skills_embeddings.json.gz", "rt") as f:
    skills = json.load(f)
```

```ts
// Node.js
import { createReadStream } from 'node:fs'
import { createGunzip } from 'node:zlib'
import { pipeline } from 'node:stream/promises'

let buf = ''
await pipeline(
  createReadStream('esco_taxonomy/outputs/skills_embeddings.json.gz'),
  createGunzip(),
  async function* (src) { for await (const c of src) buf += c },
)
const skills = JSON.parse(buf)
```

```go
// Go
f, _ := os.Open("esco_taxonomy/outputs/skills_embeddings.json.gz")
gz, _ := gzip.NewReader(f); defer gz.Close()
var skills []Skill
json.NewDecoder(gz).Decode(&skills)
```

---

## What each dataset is for

| Dataset | Primary use cases |
|---|---|
| **Locations** | User addresses, job-posting locations, geo-radius search, country/state dropdowns, distance-based ranking. PostGIS-backed for GIS queries. |
| **ESCO taxonomy** | Resume parsing → normalized occupation / skill URIs. Semantic matching ("Python backend dev" → ESCO occupation). Skill-overlap ranking of applicants per job. |
| **Institutions** | Education history dropdowns. **Verifying a user is a real student / alumnus by matching their email domain against the institution's domain list.** Fuzzy university search. |
| **Sectors & industries** | Tagging companies and job postings with NAICS codes. Filtering by sector. Industry-based ranking signal. |
| **Qualifications** | User profile "highest qualification" field. Job posting "minimum qualification" filter. ISCED level comparisons (`isced_level >= 6` for graduate-and-above). |
| **Fields of study** | Education history tagging. Job posting field-of-study filters. Narrow-to-broad roll-up queries (e.g. any ICT narrow field → broad field `06`). |

Each folder's README has the detailed schema, the seeding recipe (with Prisma
/ Django / SQLAlchemy snippets), and the canonical query patterns.

---

## Consuming the JSON from your application

The pattern is the same in every framework:

```text
read <domain>/outputs/<file>.json
in batches of 500-1000 rows:
    INSERT INTO <table> (...) VALUES (...)
    ON CONFLICT (<natural_key>) DO UPDATE SET ..., updated_at = NOW()
```

Two cross-cutting choices the per-folder READMEs build on:

### 1. PostGIS for geo

For locations, store points as `GEOGRAPHY(Point, 4326)`. Distance queries
become one-liners (`ST_DWithin(location, ..., 50000)`) with a real spatial
index instead of full-table scans. See `locations/README.md` for the column
recipes and the longitude-first gotcha.

### 2. Bring-your-own embedding service for ESCO

The ESCO outputs ship with 256-d Gemini embeddings precomputed. You don't
have to use them. If you'd rather:

- **Avoid an embedding API entirely** — use a local model like
  `sentence-transformers/all-MiniLM-L6-v2` (Python) or `@xenova/transformers`
  (Node). Free, runs in-process, no per-call cost.
- **Use a different vendor** — re-embed the JSON once at seed time with
  OpenAI / Cohere / Voyage / etc.

`esco_taxonomy/README.md` has the recipe in both Python and TypeScript. The
only invariant: **whichever model you pick for seeding, use the exact same
one to embed incoming queries at runtime.** Mixing models breaks similarity.

Crucially, the matching path itself never calls an LLM. Embeddings are
generated at ingest (once per resume / job-post / per ESCO release) and the
ranking step is pure SQL — see `esco_taxonomy/README.md` for the query.

---

## How the datasets compose

A realistic schema in your application would foreign-key across all four:

```text
users
  id, email, country_code → location_country.iso2, ...

worker_education
  worker_id → users.id
  university_id → universities.id          -- from universities/
  verified_via_email_domain BOOL           -- see universities/README.md
  qualification_id → qualifications.id     -- from qualifications/
  field_of_study_code → fields_of_study.code  -- from fields_of_study/
  country_code → location_country.iso2

worker_experience
  worker_id → users.id
  occupation_uri → occupations.concept_uri -- from esco_taxonomy/
  industry_code → industries.code          -- from sectors/
  city_id → location_city.id               -- from locations/
  start_date, end_date

worker_skills
  worker_id → users.id
  skill_uri → skills.concept_uri           -- from esco_taxonomy/

job_postings
  industry_code → industries.code
  city_id → location_city.id
  min_qualification_id → qualifications.id
  field_of_study_code → fields_of_study.code

job_required_skills
  job_id, skill_uri → skills.concept_uri, relation_type
```

Every foreign-key target above is a row this repo seeds. The application
owns everything to the left of the arrow.

---

## Adding a new dataset

The convention each folder follows:

1. Make a folder: `<dataset>/`.
2. Add `fetch.py` (or `build.py`) — a single Python script that downloads /
   parses the upstream and writes JSON to `<dataset>/outputs/`.
3. Add `<dataset>/README.md` documenting:
   - What the dataset is and what use cases it serves.
   - The output JSON shape (`outputs/foo.json`).
   - The recommended database schema (framework-agnostic).
   - The seeding pattern (with at least one ORM example).
   - Common queries.
   - Refresh cadence.
4. Add the script's CLI to the top-level "How to run everything" block above.

Keep Python out of the consumer's view — the only thing they should ever read
is the JSON in `outputs/`.
