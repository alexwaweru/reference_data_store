# ESCO Taxonomy

Occupations and skills reference data sourced from
[ESCO](https://esco.ec.europa.eu/) (the European multilingual classification
of Skills, Competences and Occupations). Used to match free-text resume
content to a stable taxonomy so:

- Job seekers can be tagged with normalized occupations and skills.
- Job postings can declare required skills as a portable set of URIs.
- Applicants can be ranked against a posting by skill overlap, not by string
  similarity (which is brittle).

Same contract as the rest of the repo: **Python is only used for scripting.**
The JSON in `outputs/` is the consumer-facing artifact.

---

## How to (re)build

```bash
python esco_taxonomy/build.py                # build any missing outputs
python esco_taxonomy/build.py --force        # rebuild everything
python esco_taxonomy/build.py --only nested  # build only nested_occupations_skills.json
```

The script reads from `inputs/` (raw ESCO indexes plus precomputed embedding
`.npy` files) and writes to `outputs/`. It's idempotent — re-running with no
flags is a no-op.

### Large files (gzip workflow)

Two artifacts in this folder exceed GitHub's 100 MB per-file limit and are
committed only as `.gz`:

- `inputs/ESCO_occup_skills.json` → `…json.gz` (164 MB → 15 MB)
- `outputs/skills_embeddings.json` → `…json.gz` (104 MB → 35 MB)

`build.py` reads `.json.gz` transparently when the uncompressed sibling is
missing, and re-emits the `.gz` whenever it writes an output above the
50 MB threshold — so on a fresh clone you can either:

```bash
python tools/decompress.py                # inflate everything once, then work normally
# …or skip decompression entirely; build.py and your seeder can both read .gz directly
```

See the top-level README's "Large files" section for the consumer-side
read-from-gz one-liners (Python / Node / Go).

---

## Outputs (the contract)

| File | Rows | Purpose |
|---|---|---|
| `outputs/occupations_embeddings.json` | ~3,000 | One row per ESCO occupation with its 256-d embedding inlined. Seed → `occupations` table. |
| `outputs/skills_embeddings.json` | ~13,000 | One row per ESCO skill / competence with its 256-d embedding inlined. Seed → `skills` table. |
| `outputs/nested_occupations_skills.json` | ~3,000 | Each occupation enriched with its `essentialSkills[]` / `optionalSkills[]` links. Seed → `occupation_skills` edge table. |

### Record shapes

`outputs/skills_embeddings.json`:
```json
{
  "preferredLabel": "manage musical staff",
  "altLabels": ["manage staff of music", "direct musical staff"],
  "conceptUri": "http://data.europa.eu/esco/skill/0005c151-...",
  "skillType": "skill/competence",
  "embedding": [0.012, -0.044, "... (256 floats)"]
}
```

`outputs/occupations_embeddings.json`:
```json
{
  "conceptType": "Occupation",
  "conceptUri": "http://data.europa.eu/esco/occupation/00030d09-...",
  "iscoGroup": "2654",
  "preferredLabel": "technical director",
  "altLabels": ["technical and operations director", "head of technical"],
  "description": "...",
  "code": "2654.1.7",
  "embedding": [0.031, 0.008, "... (256 floats)"]
}
```

`outputs/nested_occupations_skills.json`:
```json
{
  "conceptUri": "http://data.europa.eu/esco/occupation/00030d09-...",
  "preferredLabel": "technical director",
  "essentialSkills": [
    { "uri": "http://data.europa.eu/esco/skill/591dd514-...", "title": "adapt to artists' creative demands" }
  ],
  "optionalSkills": []
}
```

---

## About the shipped embeddings

The `.embedding` arrays in the outputs were generated **once** upstream using
Google `gemini-embedding-001` at 256 dimensions. Shipping them in JSON means:

- The catalogue is loaded into your DB once and never re-embedded.
- The runtime matching path (job seeker ↔ occupation / skill) only embeds the
  *incoming query string*, then ANN-searches the warm catalogue.
- Per-match cost stays at **one ANN lookup, zero LLM calls**.

You don't have to use the shipped embeddings. See the next section.

---

## Bring your own embeddings (cheaper / self-hosted)

The Gemini embeddings are convenient but they aren't required. The
`outputs/*.json` files are usable without the `embedding` field if you'd
rather generate vectors yourself — typically because you want to:

- Avoid paying for an embedding API at all (use a local model).
- Stay in a single embedding space across occupations, skills, *and* the
  text on which you'll do search (resume bullets, job descriptions). Mixing
  spaces breaks similarity.
- Pick a different dimension (384, 512, 768, 1024) to trade index size for
  precision.

### Recipe (any language)

For each row in `occupations_embeddings.json` / `skills_embeddings.json`:

1. Build the "source context" string — typically:
   `f"{preferredLabel}. {description}. Also known as: {', '.join(altLabels)}"`
2. Pass that string to your embedding model of choice.
3. Store the resulting vector in the `embedding` column.

Do this **once per ESCO release** as a one-off batch job. Catalogue size is
~16,000 rows total — even a CPU-only local model finishes in minutes.

### Local models (no API, no cost per call)

These are the standard choices. They run inside your application process
(or a dedicated worker) and have no per-call cost beyond CPU/GPU time.

| Model | Dimensions | Notes |
|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | Tiny, fast, surprisingly good. The default for "I just want it to work." |
| `BAAI/bge-small-en-v1.5` | 384 | Slightly better quality on retrieval, similar speed. |
| `BAAI/bge-base-en-v1.5` | 768 | Bigger, better, still fits in CPU memory comfortably. |
| `Snowflake/snowflake-arctic-embed-m` | 768 | Strong on technical text — good for skills. |

Pick the model **once** and use the same one for both seeding and runtime
query embedding. Mixing models breaks cosine similarity.

### Python (sentence-transformers)

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

rows = json.load(open("esco_taxonomy/outputs/skills_embeddings.json"))
texts = [
    f"{r['preferredLabel']}. Also known as: {', '.join(r.get('altLabels', []))}"
    for r in rows
]
vectors = model.encode(texts, batch_size=64, convert_to_numpy=True)
for r, v in zip(rows, vectors):
    r["embedding"] = v.tolist()

json.dump(rows, open("esco_taxonomy/outputs/skills_embeddings.json", "w"), indent=2)
```

A worked example of this pattern (against the locations dataset, not ESCO,
but the shape is identical) lives at
`backend/location/management/commands/import_locations.py` in the Quola
repo — see the `EmbeddingGenerator` class.

### Node.js / TypeScript

Two practical options, both run in-process — no Python service needed:

**`@xenova/transformers`** — pure-JS, runs in Node or the browser, ships ONNX
weights of the same sentence-transformers models.

```ts
import { pipeline } from '@xenova/transformers'
import { readFileSync, writeFileSync } from 'node:fs'

const extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2')

const rows = JSON.parse(readFileSync('esco_taxonomy/outputs/skills_embeddings.json', 'utf8'))
for (const r of rows) {
  const text = `${r.preferredLabel}. Also known as: ${(r.altLabels ?? []).join(', ')}`
  const out = await extractor(text, { pooling: 'mean', normalize: true })
  r.embedding = Array.from(out.data as Float32Array)
}
writeFileSync('esco_taxonomy/outputs/skills_embeddings.json', JSON.stringify(rows, null, 2))
```

**`fastembed`** (Node port of Qdrant's fastembed) — slightly faster, fewer
model options. Same flow.

### API providers

If you'd rather call a hosted API: OpenAI `text-embedding-3-small` (1536-d,
or set `dimensions: 384` to match the local-model size), Cohere
`embed-english-v3.0` (1024-d), Voyage `voyage-3-lite` (512-d). Same loop —
batch 100 strings per request to stay under rate limits, persist the result
back to the JSON, seed once.

### Critical: keep the embedding model consistent at query time

Whichever model you pick for seeding, **use the exact same one to embed
incoming queries at runtime**. Cosine similarity is only meaningful within a
single embedding space. If you seed with `all-MiniLM-L6-v2` (384-d) and
query with `text-embedding-3-small` (1536-d), the dimensions don't even
match. Bake the model name into a constant somewhere and assert on it.

---

## Recommended database schema

Five tables, conceptually. Names are illustrative — call them whatever fits.
Types are described in DB terms; map to whatever your ORM uses.

### Catalogue (seeded from this folder's JSON)

```text
occupations
  concept_uri      TEXT PK                          -- ESCO URI; the join key
  preferred_label  TEXT NOT NULL, INDEXED
  alt_labels       TEXT[]
  description      TEXT
  isco_group       TEXT, INDEXED
  code             TEXT
  embedding        VECTOR(<D>) NOT NULL             -- D = dimension of your chosen model
  embedding_model  TEXT NOT NULL                    -- e.g. 'gemini-embedding-001' or 'all-MiniLM-L6-v2'

  HNSW INDEX on (embedding) USING vector_cosine_ops

skills
  concept_uri      TEXT PK
  preferred_label  TEXT NOT NULL, INDEXED
  alt_labels       TEXT[]
  description      TEXT
  skill_type       TEXT, INDEXED                    -- 'skill/competence' or 'knowledge'
  embedding        VECTOR(<D>) NOT NULL
  embedding_model  TEXT NOT NULL

  HNSW INDEX on (embedding) USING vector_cosine_ops

occupation_skills
  occupation_uri   TEXT FK → occupations.concept_uri
  skill_uri        TEXT FK → skills.concept_uri
  relation_type    ENUM('essential', 'optional'), INDEXED
  UNIQUE (occupation_uri, skill_uri, relation_type)
```

Storing `embedding_model` per-row is cheap insurance — if you ever change
embedding models, you can re-embed in place and assert against this column to
guarantee no half-migrated state ever serves a query.

### Application tables (you write to these; not seeded from here)

```text
worker_occupations                                  -- a parsed job title from a resume
  id              UUID PK
  worker_id       FK
  raw_title       TEXT
  occupation_uri  TEXT FK → occupations.concept_uri, NULL
  source          TEXT                              -- 'experience_entry', 'headline', …

worker_skills                                       -- a parsed skill from a resume
  id              UUID PK
  worker_id       FK
  raw_skill       TEXT
  skill_uri       TEXT FK → skills.concept_uri, NULL
  level           ENUM('expert','advanced','intermediate','beginner','unknown')
  source          TEXT

job_required_skills
  job_id          FK
  skill_uri       TEXT FK → skills.concept_uri
  relation_type   ENUM('essential', 'optional')
  UNIQUE (job_id, skill_uri)
```

---

## Seeding patterns (framework-agnostic)

Run in this order so foreign keys resolve:

```text
1.  load outputs/skills_embeddings.json → INSERT into skills
2.  load outputs/occupations_embeddings.json → INSERT into occupations
3.  load outputs/nested_occupations_skills.json → INSERT into occupation_skills
```

All three use `ON CONFLICT … DO NOTHING` (or the ORM equivalent) so re-runs
are safe. Batch in groups of ~500 — single inserts of vector rows are 100×
slower.

### Prisma (TypeScript)

```ts
const skills = JSON.parse(readFileSync('esco_taxonomy/outputs/skills_embeddings.json', 'utf8'))
for (let i = 0; i < skills.length; i += 500) {
  const batch = skills.slice(i, i + 500)
  const values = batch.map((s: any) =>
    `('${s.conceptUri}', ${escape(s.preferredLabel)}, ${arrLit(s.altLabels)},
      ${escape(s.skillType ?? '')},
      '[${s.embedding.join(',')}]'::vector,
      'gemini-embedding-001')`
  ).join(',')
  await prisma.$executeRawUnsafe(`
    INSERT INTO skills (concept_uri, preferred_label, alt_labels, skill_type, embedding, embedding_model)
    VALUES ${values}
    ON CONFLICT (concept_uri) DO NOTHING
  `)
}
```

Prisma can't bind the pgvector type natively — drop to raw SQL for the
embedding column. The other columns can use `createMany` if you keep
embedding writes in a separate pass.

### Django + pgvector

```python
SkillVector.objects.bulk_create(
    [SkillVector(concept_uri=s['conceptUri'], preferred_label=s['preferredLabel'],
                 alt_labels=s.get('altLabels', []), embedding=s['embedding'],
                 embedding_model='gemini-embedding-001')
     for s in skills],
    ignore_conflicts=True,
    batch_size=500,
)
```

---

## Matching at runtime (no LLM calls on the hot path)

1. **Resume / job-post ingest (once per document):**
   - For each parsed job title or skill string `s`, call `embed(s)` (one
     embedding call).
   - ANN-search `occupations` / `skills` to resolve to a `concept_uri`.
   - Write `worker_occupations` / `worker_skills` / `job_required_skills`
     with `*_uri` set.

2. **Ranking applicants for a job (zero embedding calls):**

   ```sql
   WITH job_required AS (
     SELECT skill_uri, relation_type
     FROM   job_required_skills
     WHERE  job_id = $1
   ),
   applicant_skills AS (
     SELECT ws.worker_id, ws.skill_uri, ws.level
     FROM   worker_skills ws
     JOIN   applications a ON a.worker_id = ws.worker_id
     WHERE  a.job_id = $1
   )
   SELECT
     a.worker_id,
     SUM(
       CASE WHEN j.relation_type = 'essential' THEN 2.0 ELSE 1.0 END
       * CASE a.level
           WHEN 'expert'       THEN 1.0
           WHEN 'advanced'     THEN 0.85
           WHEN 'intermediate' THEN 0.7
           WHEN 'beginner'     THEN 0.5
           ELSE 0.3
         END
     ) AS score,
     COUNT(*) FILTER (WHERE j.relation_type = 'essential') AS essential_matched,
     COUNT(*) FILTER (WHERE j.relation_type = 'optional')  AS optional_matched
   FROM job_required j JOIN applicant_skills a USING (skill_uri)
   GROUP BY a.worker_id
   ORDER BY score DESC;
   ```

   Every row touched here was resolved at ingest time. No embedding API gets
   called on the ranking path.

---

## Refresh cadence

ESCO publishes new releases occasionally (last one used here: 2024-01). When
a new release lands:

1. Drop the new CSV / JSON exports into `inputs/`.
2. Re-run the upstream embedding job to produce new `*.embeddings-256.npy`
   files (or skip this and have your application re-embed from the
   non-embedding outputs using the "Bring your own embeddings" recipe).
3. `python esco_taxonomy/build.py --force`
4. Re-seed.
