# Sectors & Industries

Industry classification reference data sourced from the
[US Census Bureau's NAICS 2022](https://www.census.gov/naics/) (2-6 digit
structure). Used for tagging companies, job postings, and worker experience
records with a canonical industry code so jobs / candidates can be filtered
and ranked by industry overlap.

Same contract as the rest of the repo: **Python is only used for scripting.**
The JSON in `outputs/` is the consumer-facing artifact.

NAICS was picked over ISIC / NACE because (a) the US Census Bureau publishes
it as a single clean XLSX with a public URL, (b) it's the de-facto standard
US/Canada/Mexico job boards already tag against, and (c) it cleanly nests
into 5 levels from broad sector down to specific national industry.

---

## How to fetch

```bash
python sectors/fetch.py            # download + parse if outputs missing
python sectors/fetch.py --force    # re-download and rebuild
```

The script downloads `2-6 digit_2022_Codes.xlsx` from `census.gov`, parses
the workbook (one row per code), and writes two JSON files. The XLSX is
cached under `.cache/` so re-runs don't hit the network.

> **Note:** The Census Bureau rejects requests with the default Python
> User-Agent (HTTP 403). The fetcher sends a browser-style UA — this is a
> public, anonymous download, no auth involved.

---

## Outputs (the contract)

| File | Rows | Purpose |
|---|---|---|
| `outputs/sectors.json` | 20 | Top-level NAICS sectors. The list most job boards show in a "Sector" dropdown filter. |
| `outputs/industries.json` | ~2,125 | Full 5-level taxonomy. Every node — sector, subsector, industry group, NAICS industry, national industry — in one flat array with `parent_code` so consumers can rebuild the tree. |

Both files use the same record shape:

```json
{
  "code": "31-33",
  "title": "Manufacturing",
  "level": "sector",
  "parent_code": null
}
```

```json
{
  "code": "311111",
  "title": "Dog and Cat Food Manufacturing",
  "level": "national_industry",
  "parent_code": "31111"
}
```

### `level` values

| Level | Code length | Count | Example |
|---|---|---|---|
| `sector` | 2 (or range like `31-33`) | 20 | `54` — Professional, Scientific, and Technical Services |
| `subsector` | 3 | 96 | `541` — Professional, Scientific, and Technical Services |
| `industry_group` | 4 | 308 | `5415` — Computer Systems Design and Related Services |
| `naics_industry` | 5 | 689 | `54151` — Computer Systems Design and Related Services |
| `national_industry` | 6 | 1012 | `541512` — Computer Systems Design Services |

### Range-coded sectors

A few sectors are stored as ranges in the upstream — `31-33` Manufacturing,
`44-45` Retail Trade, `48-49` Transportation and Warehousing — because they
span multiple 2-digit prefixes. The fetcher preserves the range string as the
`code`. The 3-digit subsectors that belong to those ranges have the range
string as their `parent_code` (e.g. subsector `311` Food Manufacturing has
`parent_code: "31-33"`). Treat `code` as an opaque string, not an integer.

---

## Recommended database schema

A single self-referential table is enough — the `level` column tells you
where in the hierarchy you are, and `parent_code` links to the row above.

```text
industries
  code          TEXT PK                          -- "311", "5415", "541512", "31-33"
  title         TEXT NOT NULL
  level         TEXT NOT NULL                    -- sector | subsector | industry_group | naics_industry | national_industry
  parent_code   TEXT NULL REFERENCES industries(code) ON DELETE SET NULL
  created_at    TIMESTAMPTZ DEFAULT NOW()
  updated_at    TIMESTAMPTZ DEFAULT NOW()

  INDEX on (parent_code)
  INDEX on (level)
```

If your application only ever cares about the 20 top-level sectors (most
common case for UI dropdowns), you can use a separate `sectors` table seeded
from `sectors.json` and skip the deeper hierarchy entirely.

### Why no embeddings?

Industry classifications are exact strings — they don't need semantic search.
The codes are short and well-known; users select from a dropdown or
auto-tag from a parser that maps free text to a code by name match (e.g.
"fintech" → "522 Credit Intermediation and Related Activities"). Save the
embedding cost for free-text data (skills, occupations) where it pays off.

If you *do* want fuzzy lookup of industries by title, add a Postgres trigram
index — it's cheaper than embeddings and good enough for "user typed
'manufactr' and meant 'manufacturing'":

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX industries_title_trgm_idx ON industries USING gin (title gin_trgm_ops);
```

---

## Linking to the rest of your schema

`industries.code` is the foreign-key target for any row that needs an
industry tag:

```text
companies
  industry_code        TEXT NULL REFERENCES industries(code)

job_postings
  industry_code        TEXT NULL REFERENCES industries(code)

worker_experiences
  industry_code        TEXT NULL REFERENCES industries(code)   -- inferred from company
```

Pick the level that matches your UX: most products tag at the 3- or 4-digit
level (subsector / industry group) — fine-grained enough to filter, coarse
enough that users actually pick the right one.

---

## Seeding patterns (framework-agnostic)

```text
load outputs/industries.json
in batches of 500:
    INSERT INTO industries (code, title, level, parent_code)
    VALUES (...)
    ON CONFLICT (code) DO UPDATE SET
      title       = EXCLUDED.title,
      level       = EXCLUDED.level,
      parent_code = EXCLUDED.parent_code,
      updated_at  = NOW()
```

**Order matters slightly:** because of the self-referencing `parent_code`,
insert with `parent_code = NULL` first if your FK is `DEFERRABLE INITIALLY
DEFERRED` isn't an option in your DB. Alternatively, sort the records by
`(level priority, code)` so sectors are inserted before subsectors etc.; the
fetch script already emits them in that order, so the naïve linear insert
works.

### Prisma (TypeScript)

```ts
const rows = JSON.parse(readFileSync('sectors/outputs/industries.json', 'utf8'))
for (let i = 0; i < rows.length; i += 500) {
  await prisma.industry.createMany({
    data: rows.slice(i, i + 500),
    skipDuplicates: true,
  })
}
```

### Django

```python
Industry.objects.bulk_create(
    [Industry(**r) for r in records],
    update_conflicts=True,
    unique_fields=['code'],
    update_fields=['title', 'level', 'parent_code'],
    batch_size=500,
)
```

---

## Common queries

The 20 top-level sectors (for a dropdown):

```sql
SELECT code, title FROM industries WHERE level = 'sector' ORDER BY title;
```

Walk down the tree from a sector:

```sql
WITH RECURSIVE subtree AS (
  SELECT code, title, level, parent_code FROM industries WHERE code = $1
  UNION ALL
  SELECT i.code, i.title, i.level, i.parent_code
  FROM   industries i JOIN subtree s ON i.parent_code = s.code
)
SELECT * FROM subtree;
```

Roll a 6-digit code up to its sector:

```sql
WITH RECURSIVE up AS (
  SELECT code, title, level, parent_code FROM industries WHERE code = $1
  UNION ALL
  SELECT i.code, i.title, i.level, i.parent_code
  FROM   industries i JOIN up ON i.code = up.parent_code
)
SELECT code, title FROM up WHERE level = 'sector';
```

---

## Refresh cadence

NAICS revisions happen every 5 years (2017, 2022, 2027…). For minor edits
between revisions, the Census Bureau publishes update files. Until the next
revision, this dataset is static — re-running the fetcher will produce
byte-identical JSON. When 2027 ships, swap the `NAICS_URL` constant in
`fetch.py` and re-run with `--force`.
