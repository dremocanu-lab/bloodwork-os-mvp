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

## The two existing revisions

- **`0001_legacy_baseline`** (`77df8fa2b964`) — the frozen, immutable
  schema of `main` at commit `397125a`, the last commit before
  interoperability. Every table/column/index/FK Bragi had before Phase 1,
  captured exactly (including a handful of harmless historical duplicate
  indexes real databases have accumulated — see the revision file's own
  comments for exactly which and why).
- **`0002_interop_phase1`** (`4cf06d926267`) — adds interoperability
  Phase 1 (see `BRAGI_INTEROP_PLAN.md`): 6 new tables + 2 additive
  nullable columns. Purely additive; nothing from 0001 is touched.

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

- **Matches the legacy baseline (0001) exactly** → `alembic stamp 0001`.
- **Matches the full Phase 1 schema (head) exactly** → `alembic stamp
  head`.
- **Anything else** (missing tables/columns, an unexpected extra object,
  a type mismatch, a partially-applied migration...) → **refuses to
  stamp**, prints the exact diff, and exits non-zero. It never guesses;
  "if tables exist then stamp head" is exactly the failure mode this
  tool exists to avoid.

If it refuses, read the diff, fix the database (or, if the model is
wrong, fix the model and write a proper migration) and re-run.

### Known, tolerated legacy differences

`backend/scripts/_alembic_baseline_fingerprint.py` names a small, fixed
set of pre-existing duplicate index names (`ix_eas_*`, `ix_eal_*`,
`ix_ec_patient` — created by the old `run_migrations()` raw SQL
alongside, redundantly, properly-named indexes SQLAlchemy's own
`create_all()` already created from the declared models) that both the
bootstrap tool and the drift check (below) explicitly tolerate. This is a
narrow, named allowlist — never a blanket "ignore unknown extras."

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
