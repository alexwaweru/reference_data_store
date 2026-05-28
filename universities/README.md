# Universities

Universities reference data, sourced from
[Hipo/university-domains-list](https://github.com/Hipo/university-domains-list).
Approximately **10,000 institutions worldwide**, each with its country, name,
and the list of email/web domains it owns.

Same contract as the rest of the repo: **Python is only used for scripting**.
The JSON in `outputs/` is the consumer-facing artifact and can be loaded by
any language / framework.

---

## How to fetch

```bash
python universities/fetch.py             # fetch if outputs missing
python universities/fetch.py --force     # re-fetch
```

The script downloads the upstream JSON, normalizes field names
(`state-province` → `state_province`, `alpha_two_code` → `country_code`),
lower-cases and de-dupes the domain list, picks a `primary_domain` (the first
domain, by convention), sorts by `(country_code, name)`, and assigns
monotonically increasing IDs.

---

## Output (the contract)

`outputs/universities.json` — ~10,000 rows.

```json
{
  "id": 1,
  "name": "Marywood University",
  "country": "United States",
  "country_code": "US",
  "state_province": null,
  "primary_domain": "marywood.edu",
  "domains": ["marywood.edu"],
  "web_pages": ["http://www.marywood.edu"]
}
```

Notes:
- **`id` is not stable across re-fetches.** Upstream has no canonical ID, so
  `id` is just the sorted row number. If you need a permanent key in your DB,
  treat `(country_code, primary_domain)` as the natural unique key — both are
  stable as long as the institution doesn't change domains.
- `domains` is always a non-empty list when present in the upstream. It's the
  field you'll use most often (see "Student verification" below).
- `country` is the display name; `country_code` is ISO 3166-1 alpha-2 and is
  the field you should foreign-key against `location_country.iso2`.

---

## Recommended database schema

One table. Pure relational — no embeddings needed since lookups are by
domain (exact match) or by name (trigram / fuzzy as needed).

```text
universities
  id                BIGSERIAL PK              -- new surrogate key; don't reuse the JSON id
  name              TEXT NOT NULL
  country_code      CHAR(2) NOT NULL          -- FK → location_country.iso2
  country_name      TEXT NOT NULL             -- denormalized; convenient for display
  state_province    TEXT NULL
  primary_domain    TEXT NOT NULL             -- the first entry from domains[]
  domains           TEXT[] NOT NULL           -- (or a child table; see below)
  web_pages         TEXT[] NOT NULL
  created_at        TIMESTAMPTZ DEFAULT NOW()
  updated_at        TIMESTAMPTZ DEFAULT NOW()

  UNIQUE (country_code, primary_domain)       -- the natural key
  INDEX  on (name) USING gin (name gin_trgm_ops)   -- fuzzy name lookup
  INDEX  on domains USING gin                       -- "find university by any owned domain"
```

If your DB doesn't have array columns (MySQL etc.), use a child table:

```text
university_domains
  university_id  BIGINT FK
  domain         TEXT NOT NULL
  UNIQUE (domain)             -- domains are globally unique
```

`UNIQUE (domain)` matters: domain uniqueness is what makes the student-email
verification flow below correct.

---

## Use case: student / alumni verification via email

The domains list is the killer feature of this dataset. When a user enters an
email address you can verify they're a student / alumnus of a real
institution **without** sending a verification SMS, calling a paid identity
provider, or asking for a student ID upload.

The flow:

1. User submits `email = "asha@students.up.ac.ke"`.
2. Send a one-time verification code to that email and require the user to
   confirm it. This proves the user controls the inbox.
3. Extract the domain: `students.up.ac.ke`.
4. Look up the domain against your `universities` table — either the exact
   domain, or the registrable suffix if you want to accept subdomains
   (`students.up.ac.ke` → match on `up.ac.ke`).

```sql
-- exact match
SELECT id, name, country_code
FROM   universities
WHERE  $1 = ANY(domains);

-- accept subdomains of known domains
SELECT id, name, country_code
FROM   universities, unnest(domains) AS d
WHERE  $1 = d OR $1 LIKE '%.' || d;
```

5. If you find a match → mark the user as `verified_student_of: university_id`
   and persist the verified email.

What this gives you, without any third-party verification cost:

- A trustworthy "verified student/alumnus" badge for profiles.
- The ability to gate features by institution (e.g. an internship board open
  only to verified students of universities in country X).
- A high-signal data point for fraud / spam screening — university domains
  are MX-controlled and hard to spoof past the OTP step.

Caveats:
- Only the act of clicking the OTP proves control of the inbox; the domain
  match proves the inbox lives at a real institution. Both are needed.
- A few universities don't expose a public domain in the dataset, and some
  countries are sparsely covered. Treat verification as "best-effort" — a
  user without a matched domain shouldn't be auto-rejected, just left
  unverified.
- Some institutions outsource student email to Gmail / Outlook for Education.
  Those students will land on `gmail.com` or `outlook.com` and can't be
  verified this way. Document this clearly in the UI.

---

## Seeding patterns (framework-agnostic)

```text
load outputs/universities.json
in batches of 500-1000:
    INSERT INTO universities (name, country_code, country_name, state_province,
                              primary_domain, domains, web_pages)
    VALUES (...)
    ON CONFLICT (country_code, primary_domain) DO UPDATE
       SET name = EXCLUDED.name,
           state_province = EXCLUDED.state_province,
           domains = EXCLUDED.domains,
           web_pages = EXCLUDED.web_pages,
           updated_at = NOW()
```

### Prisma (TypeScript)

```ts
const rows = JSON.parse(readFileSync('universities/outputs/universities.json', 'utf8'))
for (let i = 0; i < rows.length; i += 500) {
  await prisma.university.createMany({
    data: rows.slice(i, i + 500).map(u => ({
      name: u.name,
      countryCode: u.country_code,
      countryName: u.country,
      stateProvince: u.state_province,
      primaryDomain: u.primary_domain,
      domains: u.domains,
      webPages: u.web_pages,
    })),
    skipDuplicates: true,
  })
}
```

### Django

```python
University.objects.bulk_create(
    [University(**u) for u in universities],
    update_conflicts=True,
    unique_fields=['country_code', 'primary_domain'],
    update_fields=['name', 'state_province', 'domains', 'web_pages'],
    batch_size=500,
)
```

### Drizzle / SQLAlchemy

Same shape — `insert(...).onConflictDoUpdate(...)` and
`insert(...).on_conflict_do_update(...)` respectively.

---

## Common queries

Find universities in a country:

```sql
SELECT id, name FROM universities WHERE country_code = 'KE' ORDER BY name;
```

Find a university by any owned domain:

```sql
SELECT id, name, country_code FROM universities WHERE 'mit.edu' = ANY(domains);
```

Fuzzy name search (with `pg_trgm`):

```sql
SELECT id, name, similarity(name, $1) AS sim
FROM   universities
WHERE  name % $1
ORDER  BY sim DESC
LIMIT  10;
```

---

## Refresh cadence

Upstream is community-maintained on GitHub. New institutions get added a few
times per year. Re-run `python universities/fetch.py --force` periodically.
The `ON CONFLICT (country_code, primary_domain) DO UPDATE` pattern makes
re-seeds safe and incremental.
