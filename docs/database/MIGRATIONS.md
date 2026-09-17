# Database migrations

Bragi's schema is managed by **Alembic** (`backend/alembic/`). This
replaces the old approach — a `Base.metadata.create_all(bind=engine)`
call plus a ~570-line hand-written `run_migrations()` function of
idempotent `CREATE TABLE`/`ALTER TABLE`/`CREATE INDEX`/`DO $$` blocks that
ran automatically on every backend startup. That was acceptable during
early MVP development; it stopped being acceptable once real production
data existed, multiple environments existed, and schema complexity kept
growing (interoperability alone added 6 tables). `run_migrations()`'s
function body is still in `app/main.py`, **unused, kept only as a
historical reference** — every table/column it used to create is now
represented, revision-for-revision, by `alembic/versions/`.

**Application startup no longer creates or alters schema as a side
effect.** `python -m uvicorn app.main:app` (or however the backend is
started) assumes the schema already matches `alembic upgrade head` and
does nothing to fix it if it doesn't.

## The revisions on `main`

- **`0001_legacy_baseline`** (`77df8fa2b964`) — the frozen, immutable
  schema of `main` at commit `397125a`, the last commit before
  interoperability. Every table/column/index/FK Bragi had before Phase 1,
  captured exactly (including a handful of harmless historical duplicate
  indexes real databases have accumulated — see the revision file's own
  comments for exactly which and why).
- **`0002_interop_phase1`** (`4cf06d926267`) — adds interoperability
  Phase 1 (see `BRAGI_INTEROP_PLAN.md`): 6 new tables + 2 additive
  nullable columns. Purely additive; nothing from 0001 is touched.
- **`0003_phase3_hardening`** (`2398fbce8a2c`, current head on `main`) —
  6 additive, nullable/defaulted columns on `interop_connections`
  (capability caching + failure tracking). Purely additive.

Feature branches may carry additional revisions beyond head on `main` —
check `alembic history` (or `git log --oneline -- backend/alembic/versions/`)
for the current full chain rather than assuming this list is exhaustive.

**Never edit an already-applied revision file.** If something in it was
wrong, write a new migration that fixes it forward.

## Local development

### Brand-new database

```bash
cd backend
alembic upgrade head
```

Builds the exact current schema from history alone — no `create_all()`,
no manual SQL.

### Existing database (already has schema from the OLD startup code)

A database that got its schema from the pre-Alembic `create_all()` +
`run_migrations()` startup path has no `alembic_version` table and can't
just run `alembic upgrade head` (it would try to `CREATE TABLE users`
etc. against tables that already exist and fail). Use the bootstrap tool
instead — see "Bootstrapping an existing database" below.

### Running the test suite

`backend/tests/conftest.py` runs `alembic upgrade head` once per test
session automatically (only when `DATABASE_URL` is set — a pure
unit-test run with no Postgres configured works exactly as before). You
don't need to do anything extra to run `pytest` locally, as long as
`DATABASE_URL` points at a database already bootstrapped (see above) or
a brand-new one.

## Bootstrapping an existing database

```bash
cd backend
python scripts/bootstrap_alembic.py            # inspect + report only, changes nothing
python scripts/bootstrap_alembic.py --apply     # actually stamp
```

This is a **one-time, explicit, human-invoked** action — never run
automatically by the application. It inspects the live database (using
the same `alembic.autogenerate.compare_metadata` engine
`alembic revision --autogenerate` itself uses — real column/index/FK
comparison, not a bare table-name check) and classifies it into exactly
one of:

- **Matches any revision in the chain exactly** (the legacy baseline,
  interop Phase 1, ..., head) → `alembic stamp <that revision>`. Read
  from `alembic/versions/` at run time — never hardcoded — so this keeps
  working as new migrations ship, PROVIDED `REVISION_ADDITIONS` in
  `scripts/bootstrap_alembic.py` has an entry for every boundary (a
  regression test — `tests/test_bootstrap_revision_metadata.py` — fails
  the build if a new migration ships without one; the tool itself refuses
  to classify anything at all rather than risk a stale, silently-wrong
  classification).
- **Matches the one known production legacy variant exactly** (see
  "Known production legacy variant" below) → a separate, more explicit
  two-flag repair, never a bare `--apply`.
- **Anything else** (missing tables/columns, an unexpected extra object,
  a type mismatch, a partially-applied migration...) → **refuses to
  stamp**, prints the exact diff, and exits non-zero. It never guesses;
  "if tables exist then stamp head" is exactly the failure mode this
  tool exists to avoid.

If it refuses, read the diff, fix the database (or, if the model is
wrong, fix the model and write a proper migration) and re-run.

### Known, tolerated legacy differences

`backend/scripts/_alembic_baseline_fingerprint.py` names small, fixed
sets of pre-existing duplicate index names (`ix_eas_*`, `ix_eal_*`,
`ix_ec_patient` — created by the old `run_migrations()` raw SQL
alongside, redundantly, properly-named indexes SQLAlchemy's own
`create_all()` already created from the declared models) that both the
bootstrap tool and the drift check (below) explicitly tolerate. This is a
narrow, named allowlist — never a blanket "ignore unknown extras." See
"Known production legacy variant" below for the interop-era equivalent
(`KNOWN_PRODUCTION_LEGACY_EXTRA_INDEXES` / `_COLUMNS`).

## Known production legacy variant (discovered 2026-09-17)

Real production predates Alembic bookkeeping AND predates
`0003_phase3_hardening` — but it isn't a clean match for any single chain
revision either. `python scripts/bootstrap_alembic.py` alone (a bare
dry run, no flags) refused to stamp it and reported the exact diff, which
investigation traced to three distinct, unrelated causes:

- **It has the full interop Phase 1 schema** (6 tables + additive
  columns), built by the OLD interoperability-era `run_migrations()` raw
  SQL before Alembic existed, but **not yet the Phase 3 hardening
  columns** on `interop_connections`. Logically, production is "at
  `4cf06d926267`" (interop Phase 1) — not the legacy baseline, not head.
- **9 short-name duplicate interop indexes** (`ix_iic_*`, `ix_epil_*`,
  `ix_itm_*`) — the SAME kind of harmless duplication documented above
  for `ix_eas_*`/`ix_eal_*`/`ix_ec_patient`, one generation later: the OLD
  interop-era `run_migrations()` raw SQL (commit `b6d8ae9`) created these
  short-name indexes ALONGSIDE the properly-named ones SQLAlchemy's own
  models (and `0002_interop_phase1`'s migration) already declare on the
  same columns. Verified via `git log -S` against `b6d8ae9`'s own raw SQL
  — not inferred from the names. See
  `KNOWN_PRODUCTION_LEGACY_EXTRA_INDEXES`.
- **One harmless extra column**, `documents.original_layout_json` — added
  to `app/models.py` by commit `249b194`, applied to production by the
  OLD `create_all()`/`run_migrations()` startup path at the time, then
  removed from `app/models.py` by commit `6825cbb` once the discharge
  pipeline stopped needing it (`app/main.py` still reads it defensively
  via `getattr(document, "original_layout_json", None)`, never as a
  declared ORM column). Never dropped from any real database — no
  migration ever declared that removal. Confirmed 0 non-null rows on
  production as of 2026-09-17; its contents don't matter, only the column
  itself is preserved. See `KNOWN_PRODUCTION_LEGACY_EXTRA_COLUMNS`.
- **4 indexes the legacy baseline (`0001`) itself declares are MISSING**
  from production: `ix_doctor_patient_access_is_active`,
  `ix_emergency_access_sessions_public_id` (UNIQUE),
  `ix_lab_results_category`, `ix_upload_jobs_file_sha256`. Root cause:
  SQLAlchemy's `Base.metadata.create_all()` only creates missing
  **tables** on an already-existing database — it never retroactively
  adds an index that got added (via `index=True`) to a column on a table
  that already existed. These columns already existed when
  `index=True` was added to them, so `create_all()` silently never
  applied the index. See `MISSING_BASELINE_INDEXES` in
  `scripts/bootstrap_alembic.py`.

### Reconciliation flow

`backend/scripts/bootstrap_alembic.py` recognizes this ONE specific,
exact, named combination (never a loose "close enough" heuristic — any
other unexplained difference still refuses) via
`_classify_known_production_variant()`, and repairs it through an
explicit, separate two-stage flow:

```bash
cd backend
python scripts/bootstrap_alembic.py                          # Stage A — inspect only, reports the plan, NO CHANGES MADE
python scripts/bootstrap_alembic.py --repair-known-legacy --apply   # Stage B — explicit repair + stamp
```

A bare `--apply` (without `--repair-known-legacy`) intentionally does
**not** trigger this repair — it only stamps an ordinary EXACT chain
match. Requiring both flags together is deliberate: an operator who
forgets the second flag gets a safe no-op, never an unexpected partial
mutation.

Stage B (`--repair-known-legacy --apply`) does, in order, and nothing
else:

1. Refuses if an Alembic version is already stamped.
2. Re-inspects the live schema immediately before mutating and re-
   confirms it still matches the exact known variant.
3. Verifies `emergency_access_sessions.public_id` has zero duplicate
   non-null values (required before creating that index as `UNIQUE`).
4. Verifies every column the 4 missing indexes need actually exists, and
   that no index already exists under any of those 4 names with a
   different definition (fails closed rather than silently skipping via
   `IF NOT EXISTS`).
5. Creates **only** the 4 missing indexes, exactly as `0001` declares
   them.
6. Stamps `4cf06d926267` (interop Phase 1 — the logical revision this
   repaired schema now matches exactly).
7. **Stops.** It never chains into `alembic upgrade head` itself —
   `scripts/run_migrations.py` remains solely responsible for that, run
   as a separate, subsequent step.

It never drops a table, drops a column, rewrites/deletes application
rows, or runs a destructive downgrade — the only writes it performs are
the 4 `CREATE INDEX` statements and the Alembic stamp itself.

### One-time production operator sequence

Because production's Render **Pre-Deploy Command** (`python
scripts/run_migrations.py`) fails outright against this unstamped
database (`alembic upgrade head` hits `CREATE TABLE users` against a
table that already exists), the corrected bootstrap tooling has to reach
production BEFORE that pre-deploy command can succeed again — and this
tooling ships as its own small hotfix (`fix/production-alembic-
bootstrap`), independent of any feature branch, specifically so it can
deploy without also shipping unrelated application changes. The intended
sequence:

1. Temporarily disable Render's Pre-Deploy Command (dashboard → service →
   Settings → Build & Deploy) so the next deploy isn't blocked by the
   still-failing plain `alembic upgrade head`.
2. Merge/deploy **only** the small bootstrap-tooling hotfix to `main`.
   Application behavior is unchanged — this ships improved operator
   tooling only.
3. In a Render Shell against the live service, run the dry run first:
   `python scripts/bootstrap_alembic.py`. Inspect the report.
4. Only if it reports **KNOWN LEGACY PRODUCTION VARIANT** exactly as
   documented above, run the explicit repair:
   `python scripts/bootstrap_alembic.py --repair-known-legacy --apply`.
5. Then run `python scripts/run_migrations.py` to apply Phase 3+ and
   reach the current head.
6. Verify: `alembic current`, `alembic heads` (must show exactly one
   head), `python scripts/check_migration_drift.py` (must report no
   unexplained drift).
7. Re-enable Render's Pre-Deploy Command
   (`cd backend && python scripts/run_migrations.py`).
8. Perform one harmless deploy of current `main` to prove the pre-deploy
   command now succeeds on its own before merging any further feature
   work (e.g. the Clinical Document Intelligence V3 branch) that depends
   on it.

**Never** solve production being unstamped by weakening
`run_migrations.py` (e.g. adding an auto-stamp fallback) or by running
`alembic stamp head`/`alembic stamp <revision>` directly against
production without going through the classification above — both would
reintroduce exactly the "if tables exist then stamp" failure mode this
tool exists to prevent.

## Production deployment

```bash
cd backend
python scripts/run_migrations.py
```

Acquires a Postgres advisory lock (crash-safe — released automatically
if the connection drops), runs `alembic upgrade head`, releases the
lock. Use this — not a bare `alembic upgrade head` — for any real
deployment: it protects against two deploy/release steps racing the same
migration concurrently.

**[EXTERNAL ACTION]** This repository has no in-tree Render/Vercel
deployment configuration (`render.yaml`, a Procfile, etc.) — Render's
start command is configured directly in the Render dashboard, outside
this repo's control. To run migrations before a new release receives
traffic (the correct sequencing — schema must be ready before the new
code that expects it starts serving requests), configure Render's
**Pre-Deploy Command** (Render dashboard → service → Settings →
Build & Deploy) to:

```
cd backend && python scripts/run_migrations.py
```

This is a one-time manual dashboard configuration step — it cannot be
completed from this repository, and this document does not claim it has
been done. Until it is, schema changes on this codebase's next real
deploy need a manual `python scripts/run_migrations.py` run against
production by an operator with `DATABASE_URL` access, before/alongside
that deploy.

## Writing a new migration

```bash
cd backend
alembic revision --autogenerate -m "short description"
```

Review the generated file before committing — autogenerate is a
starting point, not a guarantee:

- Confirm it only contains the change you intended (no accidental
  unrelated drift from a stale local DB).
- Name any unnamed constraint Alembic left as `None` explicitly (see
  `0002_interop_phase1`'s own comment on why — an unnamed FK's
  auto-generated downgrade fails at runtime).
- For anything that isn't a pure additive change (a rename, a type
  change, a new `NOT NULL` column), use expand/contract instead of a
  single breaking migration — see "Backward compatibility" below.
- Write (or review the autogenerated) `downgrade()`. If it would be
  destructive on a database with real data, add the same kind of
  explicit `ALEMBIC_ALLOW_DESTRUCTIVE_DOWNGRADE`-style guard
  `0001_legacy_baseline.py` uses.

## Migration drift check

```bash
cd backend
python scripts/check_migration_drift.py
```

Fails (nonzero exit) if `app/models.py` has changed but no migration
represents that change — run against a database at `head`. This is a CI
gate (`.github/workflows/ci.yml`), not just a local nicety: a model
change with no matching migration is exactly the kind of thing that
silently works in a developer's already-drifted local database and then
breaks a fresh environment (or a teammate's) later.

## Backward compatibility (expand/contract)

Every migration in a real deploy sequence must be safe for the OLD
application code to keep running against, for the window between
"migration applied" and "new code deployed" (and the reverse, during a
rollback). Concretely:

- **Adding a column**: always nullable, or `NOT NULL` with a real
  default the old code doesn't need to know about. Never add a required
  column the old code can't insert around.
- **Renaming/removing a column**: expand (add the new column, backfill,
  dual-write from the app if needed) → deploy the app code that uses the
  new column → contract (a LATER migration drops the old column) — never
  rename-and-switch in one migration.
- **Changing a column's meaning**: same expand/contract shape — a new
  column/table, not a silent semantic change to an existing one old code
  still reads.

## Rollback policy

**Never run a destructive Alembic `downgrade` against a database with
real data as a "rollback."** `0001_legacy_baseline.py`'s `downgrade()`
drops every table this application has ever had — it exists so the
migration is technically reversible on a disposable test database (see
`tests/test_migrations.py`), not as a real production recovery tool. It
fails closed (raises, requires an explicit
`ALEMBIC_ALLOW_DESTRUCTIVE_DOWNGRADE=yes-i-am-sure` environment variable)
specifically to prevent this.

The real production rollback policy is:

- **Application rollback** (redeploy the previous code version) **+** a
  schema that stays backward-compatible with it, because every migration
  was written expand/contract-safe in the first place. This is why that
  discipline matters — it's what makes rollback safe without ever
  touching the schema.
- Or, if the schema itself needs to change back: a **forward-fix
  migration** (a new, reviewed revision that undoes the problematic
  change), never an Alembic `downgrade` run against production.

## Testing

`backend/tests/test_migrations.py` — real Postgres round-trip tests
(skipped gracefully without `DATABASE_URL`, or if the connected role
can't `CREATE DATABASE`; never touches the shared dev/test database other
suites use — creates and drops its own disposable scratch database per
test):

- A fresh database upgrades cleanly to `head`.
- Real sample data (users/patients/documents/lab_results) inserted at
  the legacy baseline survives the upgrade to `head` unchanged.
- `bootstrap_alembic.py` correctly recognizes a database that already has
  the full Phase 1 schema (simulating one built by the OLD
  `run_migrations()`) and stamps it to `head` with no table
  recreation — and correctly refuses a deliberately incomplete/wrong
  schema.
- The destructive-downgrade guard on `0001` fails closed without the
  override and succeeds with it.
- Downgrading just `0002` (not past the legacy baseline) is safe,
  reversible, and needs no override.

`backend/tests/test_bootstrap_known_production_variant.py` — the same
real-Postgres, disposable-scratch-database pattern, reproducing the exact
known production legacy variant above and proving: a dry run recognizes
it and mutates nothing; `--repair-known-legacy --apply` creates only the
4 missing indexes, preserves `original_layout_json` and every legacy
duplicate index, changes no application data, stamps exactly
`4cf06d926267`, and the repaired database then upgrades cleanly to head
and passes migration drift; re-running bootstrap afterward is a safe
no-op; a duplicate `emergency_access_sessions.public_id` blocks the
UNIQUE index and refuses; an unexpected extra/missing column, a wrong
index definition, an unrelated extra index, or a partially-applied Phase
3 all correctly refuse recognition; and the ordinary (non-variant) exact
matches — fresh database, legacy baseline, Phase 1, current head — still
work exactly as before.

`backend/tests/test_bootstrap_revision_metadata.py` — a regression test
with no DB dependency: `REVISION_ADDITIONS` must have an entry for every
non-head revision in the real chain (and no entry for a revision that no
longer exists) — this is what makes it impossible to silently repeat the
staleness bug that motivated the revision-keyed redesign (see
`scripts/bootstrap_alembic.py`'s `REVISION_ADDITIONS` comment).

## Emergency recovery

If a deploy applies a migration that turns out to be wrong:

1. **Do not** run a destructive downgrade against production.
2. Roll the application code back to the previous version (if the
   migration was backward-compatible, as it should have been, this is
   safe on its own).
3. Write and deploy a forward-fix migration that corrects the schema.
4. If data was affected, that's a data-recovery question, not a schema
   one — restore from a Neon point-in-time-recovery snapshot or backup,
   which is a decision for whoever owns production access, not something
   this document or an AI agent should decide unilaterally.
