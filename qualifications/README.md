# Qualifications

Education qualification reference data aligned to the
[UNESCO ISCED 2011](https://isced.uis.unesco.org/) standard (International
Standard Classification of Education). Used for tagging user profiles, job
requirements, and application filters with a canonical, internationally
comparable qualification level.

Same contract as the rest of the repo: **Python is only used for scripting.**
The JSON in `outputs/` is the consumer-facing artifact.

---

## How to build

```bash
python qualifications/build.py            # generate if output missing
python qualifications/build.py --force    # rebuild
```

The data is hardcoded in `build.py` — no network fetch is needed. ISCED 2011
has been stable since publication; the practical labels (`label`, `examples`)
cover the most common regional qualification names (UK, West Africa, France,
Germany). ISCED 0 (early childhood education) is excluded as it is not relevant
in an employment context.

---

## Output (the contract)

`outputs/qualifications.json` — 8 records (ISCED levels 1–8).

```json
{
  "id": 6,
  "isced_level": 6,
  "code": "ISCED-6",
  "name": "Bachelor's or equivalent level",
  "label": "Bachelor's degree / Graduate",
  "examples": ["BSc", "BA", "BEng", "LLB", "BTech"]
}
```

| Field | Type | Description |
|---|---|---|
| `id` | integer | Stable sequential ID (1 = lowest, 8 = highest) |
| `isced_level` | integer | UNESCO ISCED 2011 level (1–8) |
| `code` | string | Namespaced code — `ISCED-1` … `ISCED-8` |
| `name` | string | Official UNESCO level name |
| `label` | string | Short display string for UI dropdowns |
| `examples` | string[] | Illustrative regional qualification names |

### Full level map

| `id` | ISCED | `label` | Regional examples |
|---|---|---|---|
| 1 | 1 | Primary school certificate | FSLC |
| 2 | 2 | O levels / Junior Certificate | O levels, GCSE, BECE, BEPC |
| 3 | 3 | A levels / Senior Certificate | A levels, WASSCE, Baccalauréat |
| 4 | 4 | Technical / Vocational certificate | NVC, City & Guilds |
| 5 | 5 | Associate degree / HND | HND, Foundation degree, DUT |
| 6 | 6 | Bachelor's degree / Graduate | BSc, BA, BTech |
| 7 | 7 | Master's degree / Postgraduate | MSc, MBA, LLM, PGDip |
| 8 | 8 | PhD / Doctorate | PhD, DPhil, EdD |

---

## Recommended database schema

One small lookup table. No embeddings — qualifications are selected from a
finite dropdown, never searched by free text.

```text
qualifications
  id           SMALLINT PK
  isced_level  SMALLINT NOT NULL UNIQUE   -- 1-8; use for ordering and range queries
  code         TEXT NOT NULL UNIQUE       -- "ISCED-6"
  name         TEXT NOT NULL             -- official UNESCO name
  label        TEXT NOT NULL             -- display string
  examples     TEXT[] NOT NULL           -- regional equivalents
  created_at   TIMESTAMPTZ DEFAULT NOW()
  updated_at   TIMESTAMPTZ DEFAULT NOW()
```

`isced_level` is the field to use for comparison logic — e.g. "minimum
qualification: Bachelor's or higher" becomes `isced_level >= 6`.

---

## Seeding patterns (framework-agnostic)

```text
load outputs/qualifications.json
INSERT INTO qualifications (id, isced_level, code, name, label, examples)
VALUES (...)
ON CONFLICT (id) DO UPDATE SET
  isced_level = EXCLUDED.isced_level,
  code        = EXCLUDED.code,
  name        = EXCLUDED.name,
  label       = EXCLUDED.label,
  examples    = EXCLUDED.examples,
  updated_at  = NOW()
```

### Prisma (TypeScript)

```ts
const rows = JSON.parse(readFileSync('qualifications/outputs/qualifications.json', 'utf8'))
await prisma.qualification.createMany({
  data: rows.map((q: any) => ({
    id:         q.id,
    iscedLevel: q.isced_level,
    code:       q.code,
    name:       q.name,
    label:      q.label,
    examples:   q.examples,
  })),
  skipDuplicates: true,
})
```

### Django

```python
Qualification.objects.bulk_create(
    [Qualification(**q) for q in rows],
    update_conflicts=True,
    unique_fields=['id'],
    update_fields=['isced_level', 'code', 'name', 'label', 'examples'],
)
```

### SQLAlchemy

```python
session.execute(
    insert(Qualification).values(rows),
    on_conflict_do_update={
        'index_elements': ['id'],
        'set_': {c: excluded[c] for c in ('isced_level', 'code', 'name', 'label', 'examples')},
    },
)
```

---

## Linking to the rest of your schema

`qualifications.id` is the foreign key for any row that tags a qualification
level. Use `isced_level` — not `id` — in application logic so the intent is
self-documenting.

```text
user_profiles
  qualification_id    SMALLINT NULL REFERENCES qualifications(id)
  -- highest attained qualification

job_postings
  min_qualification_id    SMALLINT NULL REFERENCES qualifications(id)
  -- minimum required qualification
```

**Filtering by "at least Bachelor's":**

```sql
SELECT *
FROM   user_profiles up
JOIN   qualifications q ON q.id = up.qualification_id
WHERE  q.isced_level >= 6;
```

---

## Common queries

All qualifications ordered for a dropdown (lowest → highest):

```sql
SELECT id, label FROM qualifications ORDER BY isced_level;
```

Users who meet a job posting's minimum qualification:

```sql
SELECT u.*
FROM   user_profiles u
JOIN   qualifications uq ON uq.id = u.qualification_id
JOIN   job_postings   jp ON jp.id = $job_id
JOIN   qualifications jq ON jq.id = jp.min_qualification_id
WHERE  uq.isced_level >= jq.isced_level;
```

---

## Refresh cadence

ISCED 2011 is a UNESCO standard — it does not change between major reviews
(next review tentatively post-2030). Re-running `build.py --force` produces
byte-identical output unless `build.py` itself is edited. Updates to `label`
or `examples` (e.g. adding a new regional equivalent) only require editing the
`QUALIFICATIONS` list in `build.py` and re-running.
