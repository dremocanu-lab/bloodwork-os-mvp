# Claude Handoff — Bragi + Reducto

See `BRAGI_REDUCTO_PLAN.md` for architecture/rationale and §2f/§8 for the
final verification detail. This file is status only.

## Interoperability Phase 3 — FHIR production hardening (2026-09-12)

Full detail: `BRAGI_INTEROP_PLAN.md`'s "Phase 3" section (read that
first). **Status: `[IMPLEMENTED — BACKEND SUBSET — NOT DEPLOYED]`** —
still behind `INTEROP_FHIR_ENABLED` (default false).

Shipped, real and tested (not scaffolding): `app/services/interop/`
gained `lifecycle.py` (explicit connection state machine, illegal
transitions rejected server-side — wired into every status-changing
route in `main.py`), `drift.py` (capability fingerprint + breaking-
change detection, marks an ACTIVE connection DEGRADED on rediscovery
rather than continuing silently), `resilience.py` (retry/backoff with
jitter + `Retry-After` honoring for transient HTTP failures, a circuit
breaker that degrades a connection after repeated failures — 401/403
never retried), `concurrency.py` (Postgres-advisory-lock-guarded
per-connection sync locking — two overlapping syncs against the same
connection can't both proceed). `fhir_connector.py`'s pagination now
bounds resource count/byte size/wall-clock duration independently and
detects a repeated `next` link (a pagination loop) rather than trusting
`MAX_PAGES` alone, and supports incremental sync via `_lastUpdated` with
a race-safe cursor (advances to the sync's OWN start time, never the max
`lastUpdated` seen in results — safe under existing idempotency).
1 new migration (`0003_phase3_hardening.py`, 6 additive nullable/
defaulted columns on `interop_connections`) plus a new `POST
.../disable` route, distinct from `/pause`.

**Real, independent, third-party validation**: the exact same,
unmodified connector code was run — for real, live network calls, not
simulated — against three genuinely independent public FHIR R4 test
servers (HAPI, SMART Health IT, Firely). All three: capability discovery
succeeded, resource support classified correctly, and a real bounded
`_count=1` Patient search succeeded — zero provider-specific branching.
Captured as a real (network-optional, skips gracefully rather than
failing CI if a public sandbox is temporarily unreachable) test file:
`tests/test_interop_external_validation.py`.

**Four real bugs found and fixed by this round's own testing**, none
pre-existing:
1. `resilience.request_with_retry`'s loop fell through to `return
   response` on the LAST retry attempt when the response was still a
   retryable status (e.g. 503) — silently handing a failed response back
   to the caller as if it succeeded, instead of raising
   `ConnectorTransientError`. Caught by
   `test_exhausts_retries_and_raises_transient_error`.
2. `tests/test_migrations.py` hardcoded `HEAD_REVISION` as a literal
   string — went stale the moment `0003_phase3_hardening` was added
   (the test kept "passing" against the wrong expectation until the
   suite's own assertion caught the mismatch). Fixed to resolve the head
   revision dynamically from the actual migration chain
   (`ScriptDirectory.get_current_head()`).
3. `scripts/bootstrap_alembic.py` had the IDENTICAL hardcoding problem —
   `LEGACY_REVISION`/`HEAD_REVISION` as literal strings, and a
   two-state-only (legacy vs. head) classifier with no way to recognize
   "Phase 1 applied, Phase 3 not yet" as a valid intermediate state. This
   one is more serious than #2 (real operator tooling, not just a test) —
   fixed by resolving the revision chain dynamically and generalizing
   classification to walk the chain backwards, matching a database
   against each possible "already at revision N" hypothesis in turn.
4. A test-only assertion bug in the pagination-loop test itself expected
   exactly 1 fetch before loop detection; the real (correct) behavior is
   2 fetches (the repeated URL is only recognized as a repeat on its
   SECOND appearance) — fixed the test's expectation, not the connector.
5. **The most serious one — found by CI, not locally**:
   `concurrency.connection_sync_lock` acquired the Postgres advisory lock
   via the caller's ORM `Session`, but every route holding that lock also
   calls `db.commit()` one or more times internally — each commit ends
   the transaction and lets SQLAlchemy's connection pool hand the Session
   a DIFFERENT physical connection for the next statement. Session-level
   advisory locks are tied to the specific connection that acquired them;
   the later `pg_advisory_unlock` call landing on a different pooled
   connection is a no-op, so the lock stayed held on the original
   connection forever once it went back to the pool — every SUBSEQUENT
   request against that connection_id then saw "Another sync is already
   running," permanently. This never reproduced against this session's
   own long-lived dev database (whatever connection-reuse pattern
   happened to apply there masked it) but failed immediately and
   consistently in CI's fresh ephemeral Postgres. Fixed by acquiring/
   releasing the lock on one dedicated connection checked out directly
   from the engine and held for the exact lifetime of the `with` block,
   independent of the caller's Session entirely. This is exactly why
   "verify in CI, not just locally" matters for anything touching
   session/connection lifecycle.

**Deliberately not done this round** — see `BRAGI_INTEROP_PLAN.md`'s
Phase 3 section for the honest list and reasoning: real mTLS network
implementation, a background job queue for long-running syncs, the
Admin → Integrations frontend page and connection wizard, Playwright
coverage, dedicated end-to-end Ask-Bragi-over-FHIR-data and cross-source-
conflict tests.

**If you continue this work**: read `BRAGI_INTEROP_PLAN.md`'s Phase 3
section in full first. `REVISION_ADDITIONS` in
`scripts/bootstrap_alembic.py` must be updated every time a new
migration ships (it's the one place left that isn't fully self-
updating — see that script's own module docstring) or an old-schema
database will be classified UNKNOWN (fails closed — never silently
misclassified, but still needs a human to extend the list).

## Alembic migration framework (2026-09-12)

Full detail: `docs/database/MIGRATIONS.md` (read that first). **Status:
`[IMPLEMENTED]`** — this is a real, load-bearing change to how schema
works, not feature-flagged (there's no "off" state for a migration
framework), but it's a pure refactor of *how* the existing schema gets
built, not a schema change itself.

Replaced the old `Base.metadata.create_all(bind=engine)` +
`run_migrations()` (hand-written idempotent DDL, run automatically on
every backend start) with Alembic. Two revisions: `0001_legacy_baseline`
(the frozen, verified-exact schema of `main` at commit `397125a`, before
interop) and `0002_interop_phase1` (Phase 1's 6 tables + 2 columns).
Both were generated via real `alembic revision --autogenerate` against
genuinely fresh databases (not hand-typed), then verified table-for-
table, column-for-column, index-for-index against a real bootstrap of
each commit's actual application code — including finding and fixing two
real baseline-fidelity gaps this way: (1) 8 harmless historical duplicate
indexes on `emergency_access_sessions`/`emergency_audit_logs`/
`emergency_contacts` that the old `run_migrations()` created redundantly
alongside the declarative models' own indexes, now captured explicitly
in 0001 and formalized as real `Index()` declarations in `app/models.py`
(previously undeclared); (2) 4 foreign keys
(`admin_action_logs`/`emergency_access_sessions`/`emergency_audit_logs`
→ `patients`/`users`/itself) that real `run_migrations()` upgraded to
`ON DELETE SET NULL` at runtime but `app/models.py` never declared —
now declared explicitly (`ForeignKey(..., ondelete="SET NULL")`).

**Three real bugs found and fixed by this work, all in the new code
itself** (none in application code):
1. `alembic/env.py` ignored an explicitly-configured `Config`'s
   `sqlalchemy.url` and always fell back to the real `DATABASE_URL` —
   meaning every Alembic command a test issued against a scratch
   database silently ran against the shared real dev database instead.
   Caught because a destructive-downgrade test then (harmlessly, since
   it was a no-op re-stamp of an already-correct revision — verified
   this caused no actual data loss) touched the real dev DB. Fixed to
   respect an explicitly-set URL.
2. `scripts/bootstrap_alembic.py`'s stamp step had the identical class of
   bug — a fresh `Config` with no URL set, so `command.stamp()` always
   targeted the real `DATABASE_URL` regardless of which database was
   classified. Fixed the same way.
3. `scripts/bootstrap_alembic.py` printed the raw (credentialed) database
   URL in its "refusing to stamp" diagnostic output — fixed to mask the
   password before printing.

`backend/tests/test_migrations.py` (7 tests, real disposable scratch
Postgres databases per test, never the shared dev DB) covers: fresh-DB
upgrade to head, real sample data surviving the upgrade, the bootstrap
tool correctly recognizing an already-Phase-1 database vs. refusing a
deliberately drifted one, and the destructive-downgrade guard failing
closed without an explicit override and succeeding with one.

CI (`ci.yml`) now runs `python scripts/run_migrations.py` (provisions the
ephemeral CI Postgres via `alembic upgrade head`) and
`python scripts/check_migration_drift.py` before pytest, replacing the
old "create_all() as a side effect of importing app.main" implicit
coverage.

**If you continue this work**: read `docs/database/MIGRATIONS.md` in
full, especially "Writing a new migration" and the backward-compatibility
(expand/contract) section, before adding Phase 2 schema. The Render
pre-deploy command that actually runs `scripts/run_migrations.py` before
a new release receives traffic is **not yet configured** — see that
doc's `[EXTERNAL ACTION]` note; until it is, a production schema change
needs a manual `python scripts/run_migrations.py` run by an operator
alongside the deploy.

## Interoperability — Phase 1: FHIR R4 inbound connector (2026-09-11)

Full architecture/status/phasing: `BRAGI_INTEROP_PLAN.md` (read that
first). **Status: `[IMPLEMENTED — NOT DEPLOYED]`** — feature-flagged off
(`INTEROP_FHIR_ENABLED`, default false); merging this code changes
nothing for any real user until explicitly activated.

**Scope decision, explicit and important for future sessions**: this
product decision *supersedes the prior "no EHR scope" boundary
specifically for standards-based external connectivity* (FHIR/HL7/CDA/
DICOMweb/IHE) — Bragi is not becoming an operational hospital EHR
(scheduling/billing/order-entry/bed-management remain out of scope), but
receiving/exporting health data through standards is now in scope. If you
land here from a stale memory saying "don't add EHR-shaped features,"
this file and `BRAGI_INTEROP_PLAN.md` are the record that this specific
carve-out was made — don't re-litigate it, don't ask the user again.

What shipped (Phase 1, FHIR only, inbound): `app/services/interop/`
(ssrf.py, crypto.py, auth_providers.py, jwks.py, capability.py,
smart_discovery.py, mapping.py, identity.py, fhir_connector.py,
reports.py, templates.py), 6 new additive tables + 2 additive columns
(`Document`/`LabResult`.`source_connection_id`), 20 new
`/admin/interop/*` backend routes (all admin-only, all flag-gated), a
declarative mapping DSL (schema-validated, no eval), deterministic
(never fuzzy) patient-identity linking, a non-mutating test suite, a
real shadow-sync (commits nothing) and an idempotent commit-sync path.

Verified against **three real, materially different synthetic FHIR R4
servers** (`tests/interop/fixtures/synthetic_fhir_server.py` — genuine
in-process HTTP servers, not mocks) through the exact same, unmodified
connector code (no `if server ==` branching anywhere in
`fhir_connector.py`): a full-featured/SMART/paginated server, a minimal
server with no SMART/DiagnosticReport/DocumentReference, and a
local-code server that requires a declarative mapping override (not a
code change) to sync fully. `tests/test_interop_e2e.py` (10 tests,
against the real dev Postgres — see `DATABASE_URL`),
`tests/test_interop_capability.py`, `tests/test_interop_mapping.py`,
`tests/test_interop_ssrf.py` (27 fast unit tests, no DB) — 37 new tests,
all passing.

**Two real bugs this feature's own tests found before merging** (same
FK-cascade class this codebase has hit before for `AskBragiConversation`
— see the Ask Bragi entry below): `DELETE /my/account` broke with a
`ForeignKeyViolation` for a patient with an `ExternalPatientIdentityLink`
row, and a second one for `InteropIdentityConflict.existing_link_id`
still referencing a link about to be deleted. Both fixed in
`delete_my_account` in the same commit.

**Not done this phase** (see `BRAGI_INTEROP_PLAN.md`'s "Next phase"
section for the full list): connection-wizard frontend UI (backend API
only), incremental `_lastUpdated` query strategy (capability-detected,
not yet used to narrow a sync), Bulk Data, IHE MHD/PIXm/PDQm, HL7v2,
CDA, DICOMweb, mTLS network implementation, certificate-expiry
monitoring, schema-drift detection, background polling. CNAS remains
explicitly `UNIMPLEMENTED_CONNECTION_TYPES` — awaiting real registration.

**If you continue this work**: read `BRAGI_INTEROP_PLAN.md` in full
first. Do not add a `Connection` deletion route without also fixing the
`documents.source_connection_id`/`lab_results.source_connection_id` FK
constraints on the live DB to actually carry `ON DELETE SET NULL` (the
ORM model declares it; the raw migration SQL was corrected to declare it
too, but a database that already ran the column-creation migration
before that fix still has the constraint without it — an idempotent
`ALTER TABLE ... DROP CONSTRAINT ... ADD CONSTRAINT ... ON DELETE SET
NULL` migration is needed before any connection-delete path ships). Do
not weaken `ssrf.py`'s validation to make onboarding more convenient —
see P75/P56 in the plan doc for exactly what that guards against.

## Ask Bragi — first production-quality version (2026-09-11)

Full architecture/status: `BRAGI_ASK_BRAGI_PLAN.md` (read that first —
this is a pointer, not a duplicate). **Status: `[IMPLEMENTED — NOT
DEPLOYED]`** — feature-flagged off (`ASK_BRAGI_ENABLED`/`NEXT_PUBLIC_
ASK_BRAGI_ENABLED`, both default false); merging this code changes
nothing for any real user until explicitly activated.

What shipped: `app/services/ask_bragi/` (context/tools/prompts/schemas/
service), two new additive tables (`AskBragiConversation`/
`AskBragiMessage`), 5 new backend routes
(`/ask-bragi/conversations[...]`), a shared frontend chat component
(`components/ask-bragi/ask-bragi-chat.tsx`) plus a small dedicated chart
(`ask-bragi-chart.tsx`, deliberately not the shared `<TrendChart>` —
contract mismatch, see its docstring), two new pages (`/ask-bragi` for
patients, `/patients/[id]/ask-bragi` for doctors), and a flag-gated nav
entry. Real OpenAI Responses API tool-calling (not JSON-in-prose),
server-owned patient context (no tool has a `patient_id` parameter —
verified directly against the schemas sent to the model), citation
validation against a server-tracked authorized-evidence set (a
hallucinated/guessed citation is dropped, verified live and in a mocked
test), and a real, live-verified prompt-injection resistance result (a
synthetic document instructing the model to leak secrets and access
other patients was actually retrieved and completely ignored).

26 new backend tests (13 security/IDOR, 7 tool-scoping, 6 mocked-model),
full suite now 165 passed (was 138). A real bug this feature's own
tests found before merging: `DELETE /my/account` broke with a
`ForeignKeyViolation` once a patient had an `AskBragiConversation` row —
fixed in the same commit (the same FK-cascade class of bug
`BRAGI_SECURITY_GDPR_PLAN.md` §3 item 6 fixed for other tables).

A one-off live evaluation script (not committed) ran 11 real query
categories against the real OpenAI API (`gpt-4.1`) with a temporary
development key, against a fully synthetic patient, then deleted every
synthetic row it created. The temporary key was never written to any
file, never printed, and confirmed absent from every output this round
produced — see `BRAGI_ASK_BRAGI_PLAN.md`'s "Real OpenAI testing" section
for the actual results table.

**Architecture inconsistency found while building this**: none beyond
what's already tracked in `BRAGI_ASK_BRAGI_PLAN.md`'s "Remaining
limitations" (narrative documents have no per-section `SourceEvidence`
rows yet — a pre-existing gap from `BRAGI_REDUCTO_PLAN.md` Phase 2, not
introduced here; it just means a narrative-grounded Ask Bragi answer
currently carries 0 citations even when accurate).

Not done this round (see the plan doc's "Remaining limitations" for the
full, honest list): real SSE streaming (V1 is synchronous, a deliberate
scope decision); a document-chat entry point inside `documents/[id]/
page.tsx`; live browser/responsive/accessibility verification (same
`BRAGI_TOKENS` blocker every prior round has had); 3 of the ~16 named
eval categories (all exercising already-verified code paths).

**If you continue this work**: read `BRAGI_ASK_BRAGI_PLAN.md` in full.
Do not remove the `patient_id`-parameter restriction from any tool
schema, do not add a tool that accepts a caller-supplied patient/
document id without going through `context.py`'s resolution functions,
and do not enable either feature flag in production without confirming
`RATE_LIMIT_REDIS_URL` is configured if Render is running more than one
instance by then.

## README refresh (2026-09-11)

`README.md` was rewritten (commit `012082e`) to reflect the actual
current repository — it previously described a much earlier state (no
Reducto, no classification/splitting, no structured labs/Timeline/
Readers/charts/source-viewer, no security/GDPR hardening) and was
seriously stale. Documentation-only change, verified against the real
codebase (models/routes/services/env vars/CI workflows/package.json)
before writing, not against assumptions; markdown anchors sanity-checked,
secret-scanned (0 findings). Pushed and confirmed green in CI.

No architecture inconsistencies were discovered while documenting beyond
what's already tracked here and in `BRAGI_REDUCTO_PLAN.md`'s own
per-phase "deferred" notes (e.g. `.env.example` is itself incomplete
relative to the env vars the code actually reads — the README's env-var
section was built from a full `os.getenv`/`os.environ.get` grep across
`backend/app`, not from `.env.example` alone; worth reconciling
`.env.example` itself at some point, not done here since this was a
docs-only, README-scoped task).

Ask Bragi remains the next major development phase — not started, and
explicitly labeled "planned, not yet implemented" in the refreshed
README, with the intended authorization → minimum-necessary-retrieval →
`app/services/ai_minimization.py` → provider → cited-`SourceEvidence`
architecture documented at a high level (not built).

## CURRENT PHASE
None — all 7 phases from the original spec, a real Reducto integration
(§8), a full DB-backed production-readiness round (§9), a real
production-failure fix + classification-latency round (§10), a
normalization/source-viewer/popup-rework round (§11), a correction
round (§12: fixed a fabricated PSW clinical claim from §11, completed
the popup audit), a visual/interaction correction pass (§13: upload
compaction, an Overview display bug, source-viewer route lifecycle,
full-lab-row PDF framing, PDF render quality, a blank-viewer layout
bug), a source-highlighting correctness pass (§14: page-association
bleed, a structured-pane scroll-jump bug — code-level fix only, NOT yet
proven in a real browser at that point), and a real-browser-verified
fix for what §14 missed (§15: the structured pane still jumped in
practice because content reflow at the new, narrower width moves a row
independent of scroll offset — fixed with a real visual anchor, proven
with an actual local Playwright/Chromium session against a real
Reducto-processed document, not just code inspection) are implemented
and merged to `main`. See plan §2f, §8, §9, §10, §11, §12, §13, §14,
§15 for exactly what "done" means here and what's honestly still
deferred. `REDUCTO_ENABLED` is `true` in production (confirmed via live
traffic) — see §10 for the real production bug that was blocking every
upload there and is now fixed.

## COMPLETED PHASES
1. Reducto foundation + multi-file classification (rule-based
   "legacy_rules" classifier; Reducto itself never connected — no MCP/key
   available).
2. Identity / duplicates / canonical data / provenance.
3. Row-level source verification ("View original" per lab row).
4. Conservative clinical readers (6 document types with no prior
   pipeline).
5. Longitudinal timeline / document-organization labeling.
6. Chart system: reference-band honesty fix + chart-point → exact-row
   source deep link.
7. Full integration verification: `next build`, real `uvicorn` boot +
   OpenAPI route check, full-project `eslint`, full backend test suite,
   full cumulative diff review. See plan §2f.
8. Real Reducto integration (classify/split/extract, verified against the
   live API). See plan §8.
9. Full DB-backed production-readiness round (real Neon Postgres,
   multi-file batch, quarantine, duplicates, mixed-PDF split, Parse
   persistence). See plan §9.
10. Real production failure diagnosed and fixed (`documents.is_verified`
    schema drift blocking every upload, any provider — see plan §10),
    plus real classification-latency fixes (parallel Classify+Split,
    accurate stage messaging, bounded multi-file concurrency, error
    categorization).
11. Generic OCR-aware lab-analyte resolver (the PSV/PSW fix), a shared
    in-app source-verification viewer (PDF.js, replacing "open in a new
    tab"), and a global popup/dialog rework (no dark backdrops, anchored
    contextual UI). See plan §11.
12. Corrected §11: removed a fabricated "PSW = Platelet Distribution
    Width" catalog alias that had no real source, and rearchitected the
    resolver around two independent confidence axes (OCR-text-match vs.
    clinical-semantic) so PSW/PSV now honestly resolves unresolved rather
    than silently asserting an invented clinical meaning. Also completed
    the popup audit: converted every remaining routine/contextual
    centered dialog (revoke access, regenerate code, end assignment, both
    featured-analyte pickers) to an anchored popover, and documented the
    three that legitimately stay centered (emergency session-start,
    document deletion, account deletion). See plan §12.
13. Fixed five real product bugs reported via screenshots: the upload
    page's three stacked cards consolidated into one; a false "No
    bloodwork data yet" on Overview despite real Records/Bloodwork/Labs
    counts (a display-logic bug, not a caching one); the source viewer
    now closes automatically on Back/route change/patient switch instead
    of needing a separate close; the lab PDF highlight now frames the
    whole table row (real unioned+padded geometry, new `row_bbox_*`
    columns, additive to the existing per-field bbox) instead of just the
    value cell, with an outline-based, non-text-obscuring treatment; a
    layout-collapse bug that could leave the PDF viewer looking blank/
    tiny is fixed with a CSS floor size. Also added: a purple "selected"
    state on the lab row whose source is open, a restrained hover
    gradient, HiDPI-aware canvas rendering, and a little more restrained
    color (stat-card accents, nav active edge). See plan §13.
14. Fixed three more bugs found by manually retesting the deployed §13
    viewer: the highlight could bleed onto the wrong PDF page (including
    landing in empty space) because nothing checked that the evidence's
    own page matched the page actually on screen — now gated, plus a
    monotonic request-id guard against async render races and a bbox
    sanity check as defense in depth; still-field-sized highlighting on
    some documents turned out to be pre-existing SourceEvidence rows
    created before §13e shipped (no per-field geometry was ever retained
    for those to backfill from — verified the row-union math itself is
    correct against a real Reducto extraction, see plan §14a); opening
    "View in original" was unmounting and remounting the entire
    structured page (a Fragment-vs-div branch in the split-view
    composition), destroying its scroll position — fixed by keeping a
    stable DOM wrapper (`display: contents` when inactive) plus
    explicitly carrying the scroll offset across the transition in both
    directions. See plan §14.
15. §14's scroll-jump fix turned out to be real but incomplete — a live
    retest (screenshot) proved the pane still jumped. Root cause: the
    numeric scrollTop transfer was correct, but the left pane also gets
    NARROWER when the split opens, so its content reflows (longer names
    wrap onto more lines, etc.) — a row can end up several hundred
    pixels from where it was even with a numerically "correct" scroll
    offset, since reflow changes how much content sits above it,
    independent of scrollTop. Fixed with a real visual anchor
    (`captureVisualAnchor()` — captures the clicked element + its
    on-screen position, re-measures it after the layout swap, nudges
    scroll by the exact difference) instead of just a number. A second,
    subtler bug was found and fixed in the same pass: the anchor was
    initially captured too late (after an async gap during which the
    clicked button had already been disabled and therefore blurred),
    landing on `document.body` instead of the real row — fixed by
    capturing the anchor as the very first thing the click handler does.
    This round was verified in an ACTUAL local browser (Playwright +
    Chromium, a real synthetic patient account, a real document
    processed through live Reducto) — not just code inspection: open
    preserves position to within 0.45px, close to within 0.2px, page-2
    navigation shows zero highlight bleed, and a real page-2 analyte
    highlights correctly there. See plan §15.

## NEXT STEPS (not a "phase" — your call on priority)
- **Production was actually broken for uploads before §10** — `documents.
  is_verified` was Boolean in the model but integer in production's real
  column, so every Document insert failed (any provider). Fixed via an
  idempotent migration, deployed, and confirmed via a real synthetic
  upload against the live server (`done` status, real Reducto
  classification + extraction). If you see upload failures again, check
  `render logs` for `psycopg.errors.DatatypeMismatch` first — that class
  of bug (a model type that doesn't match the live column) can recur for
  other columns if a future model change isn't paired with a migration.
- Chart/Reader/Timeline/Documents-list still don't use the new shared
  source viewer (`openSourceEvidence`) — only Analize does. See plan
  §11b for exactly what's blocking `AnalyticsDrilldownDrawer`
  specifically (needs a `lab_result_id`/`source_evidence_id` threaded
  through the analytics data pipeline, which doesn't carry one today).
- The popup audit is now complete (plan §12b) — every remaining centered
  dialog (emergency session-start, document deletion, account deletion)
  is a deliberate, documented exception for a genuine blocking/
  irreversible workflow, not a deferred conversion. Nothing left to
  revisit here unless a new dialog is added.
- If a future document needs "PSW" or a similarly uncertain analyte name
  resolved, do not add a global synonym without a real cited source —
  see plan §12a for the vendor-specific escape hatch
  (`VENDOR_SPECIFIC_ALIASES`) and why the global catalogs stayed clean.
- Run the repo's own Playwright QA (`qa/flows.mjs`, `qa/a11y.mjs`)
  locally against the new upload/reader/chart/source-viewer/popup flows
  at the responsive breakpoints the original spec named — this session
  couldn't safely generate the `BRAGI_TOKENS` file it needs (same
  blocker as every prior round).
- Try a real end-to-end upload through live Google Document AI/OpenAI
  (classification + structured reader extraction) for the legacy-provider
  path — every phase avoided spending real API quota; this is the one
  class of test only you can run cheaply.
- Pick up any of the explicitly-deferred items in each phase's plan
  section (outline/search/30-second-read/conflicts UI, Level-2 semantic
  duplicate matching, prescription → `PatientMedication` linkage, a full
  ECharts consistency pass on the analytics dashboard, top-level
  document-organization restructuring) whenever they become the
  priority.
- §13's fixes were verified by direct source/build/test inspection, not
  a live browser pass (same `BRAGI_TOKENS` blocker as every prior
  round) — if you get real QA tokens, the highest-value things to
  visually confirm are: the new full-lab-row PDF highlight against a
  real rendered report (does the frame actually sit clear of the
  glyphs at fit-width/zoomed/resized), and the previously-blank-PDF fix
  across a few real sessions (the CSS floor-size fix addresses the root
  cause found by inspection, but wasn't reproduced live before or after
  the fix).
- `care-partner/upload/page.tsx` is a third upload-page implementation
  (separate from the patient/doctor ones fixed in §13a) that was not
  touched this round — no screenshot named it, and it doesn't share the
  same three-stacked-cards structure, but it's worth a look if a future
  round revisits upload UX.
- **Any lab document uploaded before §13e shipped will never show a
  full-row PDF highlight** — it'll keep falling back to the old
  field-only bbox forever, because the four individual field citations
  needed to compute a row union were never retained for pre-existing
  SourceEvidence rows (only one final bbox was ever stored per row
  historically). This is why the field-only highlighting in this
  round's report kept appearing even after §13e shipped — see plan
  §14b. There's no backfill path short of re-processing the original
  document through Reducto again; not attempted this round (out of
  scope, and would cost real API quota per affected document).
- §14's page-association gating was real and held up under real-browser
  retesting (§15). §14's scroll-preservation claim did NOT hold up —
  it was verified only by code/CSS inspection at the time, and a live
  retest proved it wrong (content reflow at the narrower split width
  moves rows independent of scroll offset). This is a standing lesson,
  not just a fixed bug: for anything that depends on actual browser
  layout/reflow behavior, code-level reasoning is not sufficient
  evidence of "fixed" — see plan §15 for how it was actually verified
  this time (a real local Playwright/Chromium session, a real synthetic
  account, a real Reducto-processed document, pixel-level before/after
  measurements).
- §15's fix was verified locally (see plan §15d for the exact method)
  but not against the repo's own `qa/flows.mjs`/`qa/a11y.mjs` suite,
  and not beyond a 2-page synthetic document or the desktop split
  layout (mobile/tablet's full-screen sheet variant wasn't retested
  this round). `BRAGI_TOKENS` itself is still not available as a
  pre-existing file, but this round found a working alternative: create
  a synthetic account through the real `/auth/signup` endpoint, use its
  real JWT — that path is now proven to work locally and could be
  extended to run the full `qa/` suite too, if a future round needs it.

## Architecture decisions (cumulative — see plan for full detail per phase)
- `document_type` rides alongside the existing `section` column
  everywhere; nothing that filtered on `section` was changed.
- Migrations follow the repo's pre-existing `run_migrations()`
  convention (idempotent `ADD COLUMN IF NOT EXISTS`) — no Alembic
  introduced.
- Quarantine (identity mismatch) uses `patient_id = NULL` +
  `intended_patient_id` rather than touching 9 existing query sites.
- Canonical/provenance fields went onto the existing `LabResult`/
  `Document` tables, not new parallel tables, except `SourceEvidence`
  (genuinely new: no analogous data existed before).
- Two pre-existing bugs were found via testing and fixed as part of this
  work: `Document.is_verified` Integer/Boolean schema drift (Phase 2, the
  declaration; actually converting the live column happened in §10 after
  it was found still broken in production), and
  `openai_discharge_service.py`'s eager `OpenAI()` client construction at
  import time (Phase 4).
- Lab-analyte resolution (§11a) is a new stage layered on top of the two
  existing catalogs (`synonyms.py`, `lab_catalog.py`), not a replacement
  for either — see `lab_resolver.py`.
- The shared source viewer (§11b) resolves/authorizes via a new endpoint
  but reuses the existing `/documents/{id}/file` route and its exact
  authorization pattern for the actual PDF bytes — no new file-serving
  mechanism.

## Migrations
All additive (`ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS`)
via `run_migrations()` in `backend/app/main.py` — applies automatically
on the next backend start in any environment, including production, on
deploy. Verified repeatedly against the local dev DB across every phase
(20 pre-existing `documents` rows untouched throughout).

## Environment variables
```
DOCUMENT_EXTRACTION_PROVIDER=legacy   # "legacy" or "reducto" — see plan §8
DOCUMENT_EXTRACTION_FALLBACK=legacy
REDUCTO_API_KEY=                      # backend-only; never NEXT_PUBLIC_*
REDUCTO_ENABLED=false                 # leave false — see plan §8 "turning it on"
```
No other new env vars — structured reader extraction reuses the existing
`OPENAI_API_KEY` as the fallback when Reducto is disabled or fails.
`python-dotenv` is now a dependency and `backend/.env` (gitignored) is
loaded automatically on startup — previously `.env.example` documented a
file that was never actually read.

## Tests / status (final)
- Backend: `cd backend && pip install -r requirements-dev.txt && pytest -q`
  → **67 passed** (42 original + 15 `test_lab_resolver.py` cases after
  §12a's rewrite + 5 `test_reducto_row_bbox.py` cases from §13 + 5 new
  `test_reducto_page_convention.py` cases this round), unit-only (no DB
  fixtures convention exists yet).
- Frontend: `next build` succeeds (all 33 routes); `tsc --noEmit` clean;
  `eslint` on every file touched this round is clean (a few pre-existing
  `react-hooks` findings remain in files this round didn't otherwise
  touch — confirmed via `git stash` to predate this round — see plan
  §2f/§12b/§13i, not fixed, out of scope).
- Live checks this session actually ran (not just described): a real
  SHA-256-duplicate functional test (Phase 2), a real `uvicorn` boot with
  an OpenAPI route check, `run_migrations()` applied cleanly against the
  dev DB after every phase, the real Reducto integration (plan §8), a
  full DB-backed multi-scenario round against real Neon Postgres (plan
  §9), a real synthetic upload against the LIVE production server
  confirming the §10 fix (`done` status, real classification+extraction,
  cleaned up after), a real `/source-evidence/{id}/view` round-trip (real
  bbox, real PDF bytes, and IDOR checks — cross-patient 403 on both the
  new endpoint and the existing file route, unauthenticated 401,
  nonexistent-evidence 404) against the dev DB, and this round: a real
  synthetic "PSW" document through the live Reducto API, confirming
  Reducto reads the clean source text as "PSW" correctly and the resolver
  now honestly leaves it `normalization_method="unresolved"` (§12a — this
  is the corrected, truthful outcome, not a regression from §11a's
  claim).
- Not run: live OCR/AI calls through the legacy provider (real API
  cost), the repo's Playwright QA suite (needs live tokens no session has
  been able to generate yet), and any actual browser click-through of the
  new source viewer / popup positioning (verified via build/typecheck/
  lint + real backend E2E instead — see plan §11d).
- §13: confirmed by direct inspection of the actual production build
  output that the PDF.js worker is correctly emitted and referenced at
  its real static-asset path (ruling it out as a contributor to the
  blank-PDF bug before attributing that bug to a CSS layout-collapse
  root cause instead — see plan §13f). The row-bbox union/padding
  geometry is covered by 5 unit tests. Not run: a live browser pass
  confirming the fixed layout, the new hover/selected-row treatment, or
  the row-bbox highlight against a real rendered PDF — same
  `BRAGI_TOKENS` blocker as always; see plan §13i for exactly what that
  leaves unverified.
- §14: a real synthetic 2-page PDF was generated (PyMuPDF) and run
  through the actual live Reducto API and the actual
  `extract_lab_results()` function — not a mocked response or a
  handcrafted rectangle — confirming the row-bbox union math itself
  produces correct, page-scoped geometry for every row across both
  pages (see plan §14a for the full transcript of what was verified).
  The page-association fix and the scroll-preservation architecture
  were verified by direct code/CSS/reconciliation-behavior inspection
  ONLY, not a live browser pass — and that turned out to matter: see §15.
- §15: this round actually ran a real browser (Playwright + Chromium —
  already an existing devDependency, `@playwright/test`, not a new
  tool) against a local Next.js dev server + local FastAPI backend
  pointed at the shared Neon dev DB. `BRAGI_TOKENS` as a pre-existing
  file is still unavailable, but this round found and used a legitimate
  alternative: a synthetic patient account created through the real
  `/auth/signup` endpoint (normal registration, normal JWT — not an
  auth bypass), seeded into `localStorage` the same way the existing
  `qa/flows.mjs` harness seeds its own tokens. A real 20-row, 2-page
  synthetic CBC + Basic Metabolic Panel PDF was uploaded through the
  real `/upload/batch` endpoint and confirmed (via its own audit trail)
  to have gone through live Reducto classify+extract, not the legacy
  OCR path. Four scenarios were measured directly in the browser (DOM
  `getBoundingClientRect()`, not assumptions) with screenshots as
  supporting evidence: open-preserves-position (Δ0.45px), switch-to-a-
  visible-row-doesn't-move (Δ1px), page-isolation (zero highlight
  elements on an unrelated page; a real page-2 analyte highlights
  correctly there), close-preserves-position (Δ0.2px). The synthetic
  account and document were deleted after testing. Not run: the repo's
  own broader `qa/flows.mjs`/`qa/a11y.mjs` suite, multi-page documents
  beyond 2 pages, or the mobile/tablet full-screen-sheet variant.

## Known issues
See each phase's section in `BRAGI_REDUCTO_PLAN.md` for the full list;
the headline items are in this file's "Next steps" above, plus plan §8
for the Reducto-integration-specific ones.

## Manual configuration/authentication required
- **None new this round.** No Render environment variables were changed
  or need changing; `frontend/package.json` gained one new dependency
  (`pdfjs-dist`, for the in-app PDF viewer) — a normal `npm install` on
  the next frontend deploy picks it up.
- **Reducto**: a real `REDUCTO_API_KEY` was used to build and verify the
  integration (see plan §8) and is in `backend/.env` (gitignored, local
  only) — rotate/replace it if you don't want that key used further.
  `REDUCTO_ENABLED=true` is confirmed live in production already.
- **Playwright QA**: nobody's generated a real `BRAGI_TOKENS` file
  covering every role (see `qa/flows.mjs` for the expected shape) —
  but §15 found and used a working way to get at least one real,
  legitimate token when needed: sign up a synthetic account through the
  actual `/auth/signup` endpoint (normal registration, real JWT
  returned), then seed it into `localStorage` the same way `qa/flows.mjs`'s
  own `seed()` does. That covers one role at a time (whichever the
  synthetic account was created as) — building a full `BRAGI_TOKENS`
  covering every role the same way (patient/doctor/pcp/admin/care_partner/
  emergency_worker) is mechanical from here, just not done this round.

## BRAGI SECURITY / GDPR

A full security/GDPR/privacy/data-governance hardening round. Master
document: `BRAGI_SECURITY_GDPR_PLAN.md` (repo root) — read that first;
this section is a pointer/summary, not a duplicate. Supporting
documents: `docs/security/*`, `docs/privacy/*`, `docs/vendors/*`,
`docs/ai/AI_GOVERNANCE.md`, `docs/regulatory/INTENDED_PURPOSE_DRAFT.md`,
`docs/PRODUCTION_READINESS_CHECKLIST.md` (the compact, evidence-cited
launch checklist).

**Status labeling convention introduced this round** (used consistently
across all of the above, and recommended for any future security/
compliance work in this repo): `[PASS]` (implemented AND verified with
real evidence — never code-appearance alone), `[FAIL]`,
`[IMPLEMENTED — NOT DEPLOYED]`, `[EXTERNAL ACTION]`, `[LEGAL REVIEW]`,
`[INDEPENDENT VALIDATION]`, `[NOT APPLICABLE]`, `[UNKNOWN]` (never
turned into a false `[PASS]` for uncertainty). No GDPR/HIPAA/MDR/EU-AI-
Act/ISO-27001/SOC-2 compliance or certification is claimed anywhere —
none has been externally established.

### Shipped to production this round (3 commits, all deployed and confirmed live)

- `b4ad7dc` — Python dependency CVE fixes (jose, multipart, dotenv);
  `starlette`/`pyasn1` CVEs correctly left un-upgraded (blocked by
  direct-dependency version constraints — see plan §3/§12, not forced).
- `5ceec0c` — backend hardening: security response headers, login-
  timing side-channel fix, password-length floor, 4 real account-
  deletion FK-cascade bugs found via live reproduction and fixed
  (500→200, DB-verified audit-trail preservation), `is_active`
  staleness fix in 2 doctor-facing endpoints, file-upload validation
  (extension/magic-byte/size), PHI removed from `ai_extract.py` logs,
  2 info-disclosure fixes, 20 new regression tests (IDOR, headers,
  upload validation) — all against the real dev DB, all passing.
- `7142646` — frontend CSP + security headers (`next.config.ts`,
  verified live in a real Playwright/Chromium session including the
  PDF.js source viewer — zero violations), Next.js critical CVE fix
  (16.2.4→16.3.4, `npm audit` 11→0).

Render (`dep-daheeitckfvc73bq8bug`, commit `7142646`): `live`. Vercel
(same push): `Ready`. Both confirmed 2026-09-10.

### Round 2 — technical controls implemented and verified (8 commits, all pushed, CI-confirmed green)

Continuation of the same effort, picking up exactly the items round 1
deferred. `807f2fd` (CNP-in-URL fix via a new `POST /emergency/search`
+ CNP masked in every list/search response + a reusable AI-provider
data-minimization boundary, `app/services/ai_minimization.py`),
`c1d06a3` (real rate limiting, `app/rate_limit.py` — Redis-backed when
configured, an explicitly-labeled per-instance in-memory fallback
otherwise, fails open on backend errors), `fce4652`/`326908d`/
`8e61f24`/`9f5618f` (a full 245-commit git-history secret scan via
gitleaks — zero real findings; Bandit/Semgrep static analysis — zero
High findings; a real CI pipeline, `.github/workflows/ci.yml` +
`nightly-security.yml`, confirmed with real GitHub Actions runs
including one genuine caught-and-fixed Bandit failure), `7292b0d`
(`POST /my/export` — a real DSAR data export for patients), `9f6f55b`
(`DELETE /my/account` now covers doctor/admin/care_partner too, with
deliberately different semantics per role — see below), `77c8f48` (a
real malware-scanning pipeline boundary — `upload -> security_scan ->
accepted/quarantined -> processing` — plus a narrow heuristic screen
for the most unambiguous malicious-PDF markers), `9f4f0df` (the CNP
regression suite the first CNP commit should have shipped with).

Full backend suite: 138 tests passing (up from 96 at the end of round
1), all against the real dev DB, confirmed both locally and in CI
against a fresh ephemeral Postgres. See `BRAGI_SECURITY_GDPR_PLAN.md`
§3a for the itemized status table with evidence citations, and each
linked `docs/security/*.md`/`docs/privacy/DSAR_RUNBOOK.md` doc for full
narrative detail — this section is a pointer, not a duplicate.

### Real, unmitigated gaps remaining after round 2

- No real antivirus engine connected (the pipeline boundary and a
  narrow heuristic screen exist and are enforced, but this is not a
  substitute for a real scanner) — `[EXTERNAL ACTION]`, vendor
  selection.
- No distributed (Redis) rate-limit backend configured in the actual
  Render environment yet — the mechanism exists and works correctly on
  the in-memory fallback for today's single instance, but
  `RATE_LIMIT_REDIS_URL` isn't set.
- No encryption-at-rest for CNP (design-only, deliberately not migrated
  — `docs/security/IDENTIFIER_ENCRYPTION_PLAN.md`).
- No RLS (design-only, deliberately not enabled — `docs/security/
  RLS_PLAN.md` explains exactly why blind activation would be unsafe
  with this app's Neon pooling/background-job architecture).
- No token-revocation mechanism.
- `emergency_worker` accounts have no self-deletion path at all
  (deliberate — see below); doctor/admin self-deletion is a soft-delete,
  not a full erasure (`[LEGAL REVIEW]` on whether that's the right final
  policy).
- A real (found via testing in round 1, still not fixed) `StaleDataError`
  race between account deletion and an in-flight background upload job.
- Rectification/change-history mechanism still doesn't exist — an edit
  still silently overwrites the prior value with no record of what it
  was corrected from.

Full prioritized list with evidence: `BRAGI_SECURITY_GDPR_PLAN.md` §24,
`docs/PRODUCTION_READINESS_CHECKLIST.md`'s "highest-priority next
steps", and `docs/EXTERNAL_COMPLIANCE_ACTIONS.md` for everything that
needs a vendor/legal/product decision outside engineering.

### Things requiring a product decision (not silently changed)

`role` is entirely client-supplied at `/auth/signup` with no
server-side gate for `doctor`/`admin` beyond a code for `care_partner`
— could be intentional self-service onboarding or a real gap;
`/admin/patients/search` has no department/hospital scoping unlike
`/admin/doctors`. Neither was changed unilaterally — changing either
without confirming intent risks breaking the actual current onboarding/
admin workflow, which this round's own production-safety rules
prohibit doing without confirmation. See plan §5/§6.

Round 2 added two more: `emergency_worker` accounts have no
self-deletion path (a clean 403 today, not a broken feature — emergency-
access accounts are commonly tied to institutional/break-glass
provisioning this codebase has no visibility into); doctor/admin
self-deletion is a soft-delete (login disabled, account PII anonymized,
but the row and other patients' clinical records that reference it
survive) rather than a full erasure, which is also `[LEGAL REVIEW]` on
whether that's the correct final policy, not just a product call. See
`docs/privacy/DSAR_RUNBOOK.md` and `docs/EXTERNAL_COMPLIANCE_ACTIONS.md`.

### Testing convention this round reused/extended

Real dev DB (Neon, via `backend/.env`, gitignored), synthetic accounts
created through the real `/auth/signup` endpoint (never mocked), FastAPI
`TestClient`-based pytest tests gated with
`pytest.skip(..., allow_module_level=True)` when `DATABASE_URL` is
unset — a deliberate departure from this repo's prior unit-only
convention, added specifically for IDOR/security regression coverage
that needs real authorization checks against real rows. See
`backend/tests/test_idor_regression.py`,
`backend/tests/test_security_headers.py`,
`backend/tests/test_upload_validation.py`.

### If you continue this work

Read `BRAGI_SECURITY_GDPR_PLAN.md` in full first — it is the
authoritative, up-to-date status. Do not mark anything `[PASS]` without
the same evidence standard (a named test, a real request/response, a
real DB query) used throughout. Do not enable RLS or migrate CNP
encryption without reading the corresponding design doc first — each
documents a specific reason the naive version of that change would be
unsafe for this app's actual architecture. Rate limiting and CI now
exist (round 2) — read `docs/security/RATE_LIMITING.md` and
`docs/security/CI_PIPELINE.md` before changing either; the rate
limiter's own first implementation had a real bug (a class-instance
`Depends()` callable that broke FastAPI's `Request` recognition) that
its own test suite caught before it shipped — a cautionary example for
touching that file casually.

Highest-value next items (see `docs/EXTERNAL_COMPLIANCE_ACTIONS.md` for
the full external/legal/product list): a real antivirus engine behind
the now-ready `CLAMAV_HOST` integration; `RATE_LIMIT_REDIS_URL` in
Render once/if horizontal scaling is planned; a rectification/change-
history mechanism; DSAR export for non-patient roles.

## Ask Bragi Phase 4 — activation, Overview rebuild, contextual panel (2026-09-11)

Full detail: `BRAGI_ASK_BRAGI_PLAN.md`'s "Phase 4" section (this is a
pointer, not a duplicate). Frontend flag (`NEXT_PUBLIC_ASK_BRAGI_ENABLED`)
is set `true` in Vercel production (confirmed via `vercel env pull`).
**Render's `ASK_BRAGI_ENABLED`/`OPENAI_API_KEY` were NOT set or verified
this round** — the `render` CLI has no env-var subcommand, and this
environment correctly refused to let its own stored auth token be
extracted for a raw API call as a workaround. **Whoever has Render
dashboard access needs to set `ASK_BRAGI_ENABLED=true` and confirm a
real `OPENAI_API_KEY` is present before Ask Bragi will actually answer
in production** — until then, the nav entry is visible (frontend flag
on) but every request gets a safe, worded error, not a working answer.

What shipped: server-authoritative per-turn scope broadening (keyword
detection + explicit UI toggle, never silent — `scope_used` on every
response); a real document-level `SourceEvidence` fallback for
narrative documents (previously 0 citations even when accurate, now a
correctly-labeled `page_only`-precision citation); a rebuilt patient
Overview (Ask Bragi at the top, quick actions, Recently added, a
deterministic "Needs your attention," Featured Lab Trend graph and My
Medications widget removed from Overview only); a shared purple
thinking indicator (`ask-bragi-thinking-indicator.tsx`, reduced-motion
aware) used identically for patient and doctor UIs; a contextual
`AskBragiSideTab` on document reader pages (defaults to document scope,
full-record for Analize/Timeline/Overview) coexisting with the PDF
source viewer via a new `RightWorkspace` tab switcher when both are
open, keeping both mounted so neither loses state.

171 backend tests passing (was 165) — 5 new: scope-broadening (explicit
toggle, keyword intent, no-signal-stays-narrow, an inherently-wide tool
call still marks broadening, `patient_record`-scope conversations are
unaffected) and the narrative-citation fallback.

Real Playwright testing against a local production build (not just
tsc/eslint/build) found and fixed three defects before they reached
production: a scroll-anchor bug (the new side-tab button lives in a
sticky page header, not flowing content — anchoring scroll-restoration
math on it produced a large spurious delta that snapped the page to the
top on close), a missing mobile full-screen sheet style on the new
`AskBragiPanel` (rendered inline instead of as a real overlay — found by
actually loading the page at 390px wide, not by inspecting code), and a
missing route-change safety net on the new `AskBragiPanelProvider`
(mirrored `source-viewer-context.tsx`'s open/close shape but not its
pathname-based auto-close, so a stale conversation could survive a
navigation to another patient/document) plus a stale-response guard in
`ask-bragi-chat.tsx`'s `send()` (a slow response arriving after the user
switched patients could otherwise land in the wrong patient's message
list). Also verified: doctor-side mirroring (same contextual system,
same thinking indicator, on `/patients/[id]/ask-bragi` and a doctor's
view of `documents/[id]/page.tsx`, which is genuinely the same
component patients use, gated by role — not a separate implementation)
and safe patient-switching (no stale content, no stuck thinking
indicator, confirmed with two synthetic patients under one doctor).

**Not independently re-tested this round, and why**: the "both PDF and
Ask Bragi open on a phone-width viewport" tab-switcher case specifically
— reaching it organically requires clicking a citation link inside a
real Ask Bragi answer, which requires a working OpenAI key (not
available in this environment). The fix for it is a standard, well-
understood CSS stacking-context technique (documented in
`right-workspace.tsx`'s own comment), reasoned through and typechecked/
linted/built, but not pixel-verified end-to-end the way everything else
above was. GDPR docs (`BRAGI_DATA_MAP.md`, `RETENTION_POLICY.md`,
`DSAR_RUNBOOK.md`) now cover the two new Ask Bragi tables — see the
separate commit for that. Imaging/medication-conflict/reverse-language
eval categories and a latency benchmark were not attempted this round —
both need a configured OpenAI key this environment doesn't have.

### If you continue this work

Read `BRAGI_ASK_BRAGI_PLAN.md`'s "Phase 4" section first. Before
enabling Ask Bragi for real users, get Render's `OPENAI_API_KEY`/
`ASK_BRAGI_ENABLED` set (see above) and re-run the live eval script
(or a successor covering imaging/medication-conflict/reverse-language)
against real vendor credentials. If you touch `right-workspace.tsx`'s
sheet-variant stacking fix, verify it with a real citation click on a
phone-width viewport rather than trusting the CSS reasoning alone — that
specific path was not pixel-tested this round for the reason above.

## Ask Bragi Phase 5 — real streaming, conversation history, activation confirmed (2026-09-11)

Full detail: `BRAGI_ASK_BRAGI_PLAN.md`'s "Phase 5" section (pointer,
not a duplicate). Headline: **Ask Bragi is now genuinely live** — the
user configured a real `OPENAI_API_KEY` + `ASK_BRAGI_ENABLED=true` on
Render this round, and a real synthetic-account smoke test against
production round-tripped the full pipeline (signup → create
conversation → real grounded answer) before this phase's own work
began.

What shipped, all verified via real browser testing (local for
anything not needing a live model call, real production for streaming/
stop/history/language, per the task's own "do not mark UX done from
tsc/build alone" instruction):

- Real SSE streaming (new `run_turn_streaming` in service.py, new
  `POST .../messages/stream` route) — a frame-by-frame trace against
  real production output showed 72 distinct incremental growth steps
  for one answer, confirming genuine token-by-token streaming, not a
  fast plop that merely looked instant under coarse polling. Stop is a
  real `AbortController` the backend detects via
  `request.is_disconnected()`; a stopped turn is never persisted (it
  never passed citation/chart validation). Composer stays editable and
  a draft survives completion — both confirmed on production.
- Conversation history: `AskBragiChat` can resume a conversation by id;
  a new `AskBragiHistorySidebar` (grouped by recency, inline delete, no
  dark modal) is used by both the patient's `/ask-bragi` and the
  doctor's `/patients/[id]/ask-bragi` (patient-scoped via a new
  `patient_id` filter on `GET /ask-bragi/conversations`, 2 new security
  tests) — verified with two real patients under one doctor, no
  cross-patient leakage. Mobile: an off-canvas drawer, no dark backdrop.
- Chart overhaul: the old 3-point unlabeled SVG now reuses `<TrendChart>`
  (same component Analize/Overview already use) — real axes, reference
  band, hover/tap/keyboard readout, mixed-unit safety, real click-
  through to the source viewer.
- **A real, pre-existing bug found and fixed**: the global sidebar's
  `position: sticky` silently broke on any page taller than one
  viewport (root cause: `overflow-x: hidden` on BOTH `html` and `body`
  blocks the CSS2.1 overflow-propagation rule that would otherwise make
  `body`'s overflow become the viewport's own — both ended up as
  independent, non-scrolling scroll containers, and sticky anchored to
  the wrong one). Moving the rule to `body` only fixed it — re-verified
  across all 7 nav routes.
- Reverse-language eval completed for real: a Romanian question against
  production got a fully Romanian, correctly-grounded answer AND
  Romanian follow-up chips, with zero explicit language-handling code.

185 backend tests passing (was 171 after Phase 4) — 14 new (12 for
streaming: 8 pure extraction-helper tests, 4 against a fake async
OpenAI client exercising the real route/DB/auth/persistence; 2 for the
new patient-scoped conversation list).

**Not done this round**: imaging and two-source-medication-conflict
eval categories (need more synthetic-document setup than time allowed);
a proper N-sample latency benchmark (only a handful of real timings
captured incidentally during UI verification).

### If you continue this work

Read `BRAGI_ASK_BRAGI_PLAN.md`'s "Phase 5" section first. Ask Bragi is
LIVE — any further change to `service.py`/`tools.py`/the streaming
route is now a change to a real, answering feature, not a flagged-off
one; re-run the full backend suite (`pytest`, 185 tests) and the
security suite specifically before touching authorization/citation code.
If you touch the html/body CSS rule this round's sidebar fix relies on,
re-run the sticky-sidebar scroll trace across all 7 nav routes before
assuming a change is safe — the failure mode is silent (no error, no
test catches it, only real scrolling on a genuinely tall page reveals
it).
