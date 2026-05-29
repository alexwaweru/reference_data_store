# Fields of Study

Academic field of study reference data aligned to the
[UNESCO/Eurostat ISCED-F 2013](https://www.uis.unesco.org/en/topic/international-standard-classification-education-isced)
standard (International Standard Classification of Education — Fields of
Education and Training 2013). Used for tagging user education history, job
requirements, and candidate filters with a canonical, internationally comparable
field of study.

Same contract as the rest of the repo: **Python is only used for scripting.**
The JSON in `outputs/` is the consumer-facing artifact.

---

## How to build

```bash
python fields_of_study/build.py            # generate if output missing
python fields_of_study/build.py --force    # rebuild
```

The data is hardcoded in `build.py` — no network fetch is needed. No
authoritative machine-readable (JSON/CSV) distribution of ISCED-F 2013 exists
from UNESCO; the canonical source is the official
[UNESCO UIS PDF](https://www.uis.unesco.org/sites/default/files/medias/fichiers/2025/04/international-standard-classification-of-education-fields-of-education-and-training-2013-detailed-field-descriptions-2015-en.pdf).
The data here covers the broad (2-digit) and narrow (3-digit) levels — the
detailed (6-digit) level adds ~150 further rows and is available in the PDF if
needed later.

---

## Output (the contract)

`outputs/fields_of_study.json` — 41 records (11 broad + 30 narrow fields).

All records use the same shape so a single reader handles the whole file:

```json
{
  "code": "04",
  "name": "Business, administration and law",
  "level": "broad",
  "parent_code": null
}
```

```json
{
  "code": "041",
  "name": "Business and administration",
  "level": "narrow",
  "parent_code": "04"
}
```

| Field | Type | Description |
|---|---|---|
| `code` | string | ISCED-F code — 2-digit for broad, 3-digit for narrow |
| `name` | string | Official UNESCO field name |
| `level` | string | `broad` or `narrow` |
| `parent_code` | string \| null | Code of the parent broad field; null at the top level |

### Broad fields (11)

| Code | Broad field |
|---|---|
| `00` | Generic programmes and qualifications |
| `01` | Education |
| `02` | Arts and humanities |
| `03` | Social sciences, journalism and information |
| `04` | Business, administration and law |
| `05` | Natural sciences, mathematics and statistics |
| `06` | Information and communication technologies |
| `07` | Engineering, manufacturing and construction |
| `08` | Agriculture, forestry, fisheries and veterinary |
| `09` | Health and welfare |
| `10` | Services |

### Narrow fields (30)

| Code | Narrow field | Broad parent |
|---|---|---|
| `001` | Basic programmes and qualifications | `00` |
| `002` | Literacy and numeracy | `00` |
| `003` | Personal skills and development | `00` |
| `011` | Education | `01` |
| `021` | Arts | `02` |
| `022` | Humanities (except languages) | `02` |
| `023` | Languages | `02` |
| `031` | Social and behavioural sciences | `03` |
| `032` | Journalism and information | `03` |
| `041` | Business and administration | `04` |
| `042` | Law | `04` |
| `051` | Biological and related sciences | `05` |
| `052` | Environment | `05` |
| `053` | Physical sciences | `05` |
| `054` | Mathematics and statistics | `05` |
| `061` | Information and communication technologies | `06` |
| `071` | Engineering and engineering trades | `07` |
| `072` | Manufacturing and processing | `07` |
| `073` | Architecture and construction | `07` |
| `081` | Agriculture | `08` |
| `082` | Forestry | `08` |
| `083` | Fisheries | `08` |
| `084` | Veterinary | `08` |
| `091` | Health | `09` |
| `092` | Welfare | `09` |
| `101` | Personal services | `10` |
| `102` | Hygiene and occupational health services | `10` |
| `103` | Security services | `10` |
| `104` | Transport services | `10` |
| `108` | Interdisciplinary programmes involving services | `10` |

---

## Recommended database schema

One self-referential table — the same pattern as `industries` (NAICS). `code`
is the natural primary key since ISCED-F codes are globally unique strings.

```text
fields_of_study
  code         TEXT PK                               -- "04", "041"
  name         TEXT NOT NULL
  level        TEXT NOT NULL                         -- broad | narrow
  parent_code  TEXT NULL REFERENCES fields_of_study(code) ON DELETE SET NULL
  created_at   TIMESTAMPTZ DEFAULT NOW()
  updated_at   TIMESTAMPTZ DEFAULT NOW()

  INDEX on (level)
  INDEX on (parent_code)
```

Because the file is small (41 rows), no additional indexes are necessary beyond
the above. If you add the detailed (6-digit) level later, add a `gin` trigram
index on `name` for fuzzy search:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX fields_of_study_name_trgm ON fields_of_study USING gin (name gin_trgm_ops);
```

---

## Seeding patterns (framework-agnostic)

Broad fields must be inserted before narrow fields because of the self-referential
`parent_code`. The output file already emits them in this order (broad first),
so a linear insert works without two-pass logic.

```text
load outputs/fields_of_study.json
in one pass (broad rows come first):
    INSERT INTO fields_of_study (code, name, level, parent_code)
    VALUES (...)
    ON CONFLICT (code) DO UPDATE SET
      name        = EXCLUDED.name,
      level       = EXCLUDED.level,
      parent_code = EXCLUDED.parent_code,
      updated_at  = NOW()
```

### Prisma (TypeScript)

Prisma's `createMany` cannot insert self-referential rows in one shot if FK
constraints are enforced eagerly. Use two passes or wrap in a transaction with
`DEFERRABLE` FK:

```ts
const rows = JSON.parse(readFileSync('fields_of_study/outputs/fields_of_study.json', 'utf8'))

// Pass 1 — broad fields (parent_code is null)
const broad = rows.filter((r: any) => r.level === 'broad')
await prisma.fieldOfStudy.createMany({ data: broad, skipDuplicates: true })

// Pass 2 — narrow fields
const narrow = rows.filter((r: any) => r.level === 'narrow')
await prisma.fieldOfStudy.createMany({ data: narrow, skipDuplicates: true })
```

Or via raw SQL for a single-pass upsert (avoids the FK timing issue):

```ts
for (let i = 0; i < rows.length; i += 500) {
  const batch = rows.slice(i, i + 500)
  const sqlRows = batch.map((r: any) =>
    Prisma.sql`(${r.code}, ${r.name}, ${r.level}, ${r.parent_code ?? null}, NOW(), NOW())`
  )
  await prisma.$executeRaw`
    INSERT INTO fields_of_study (code, name, level, parent_code, created_at, updated_at)
    VALUES ${Prisma.join(sqlRows)}
    ON CONFLICT (code) DO UPDATE SET
      name        = EXCLUDED.name,
      level       = EXCLUDED.level,
      parent_code = EXCLUDED.parent_code,
      updated_at  = NOW()
  `
}
```

### Django

```python
FieldOfStudy.objects.bulk_create(
    [FieldOfStudy(**r) for r in rows],
    update_conflicts=True,
    unique_fields=['code'],
    update_fields=['name', 'level', 'parent_code'],
    batch_size=500,
)
```

### SQLAlchemy

```python
session.execute(
    insert(FieldOfStudy).values(rows),
    on_conflict_do_update={
        'index_elements': ['code'],
        'set_': {c: excluded[c] for c in ('name', 'level', 'parent_code')},
    },
)
```

---

## Linking to the rest of your schema

`fields_of_study.code` is the foreign-key target. Tag at whichever granularity
your UX exposes — broad for a top-level filter, narrow for profile tagging.

```text
user_educations
  field_of_study_code    TEXT NULL REFERENCES fields_of_study(code)

job_postings
  field_of_study_code    TEXT NULL REFERENCES fields_of_study(code)
```

If users pick at the narrow level but you want to filter at the broad level,
join through `parent_code` rather than storing both codes:

```sql
SELECT u.*
FROM   user_educations ue
JOIN   fields_of_study fn ON fn.code = ue.field_of_study_code   -- narrow
WHERE  fn.parent_code = '04';   -- match any Business, admin & law narrow field
```

---

## Common queries

All broad fields for a top-level dropdown:

```sql
SELECT code, name FROM fields_of_study WHERE level = 'broad' ORDER BY code;
```

Narrow fields under a chosen broad field:

```sql
SELECT code, name
FROM   fields_of_study
WHERE  parent_code = $1
ORDER  BY code;
```

Walk up from a narrow code to its broad field:

```sql
SELECT parent.code, parent.name
FROM   fields_of_study child
JOIN   fields_of_study parent ON parent.code = child.parent_code
WHERE  child.code = $1;
```

Count user profiles per broad field:

```sql
SELECT fb.name AS broad_field, COUNT(*) AS profiles
FROM   user_educations ue
JOIN   fields_of_study fn ON fn.code = ue.field_of_study_code
JOIN   fields_of_study fb ON fb.code = fn.parent_code
GROUP  BY fb.name
ORDER  BY profiles DESC;
```

---

## Refresh cadence

ISCED-F 2013 is a UNESCO/Eurostat standard — it does not change between major
reviews. Re-running `build.py --force` produces byte-identical output unless
`build.py` itself is edited. If the detailed (6-digit) level is needed in
future, add the `DETAILED_FIELDS` list to `build.py` following the same pattern
and append them to `records` in `run()`.
