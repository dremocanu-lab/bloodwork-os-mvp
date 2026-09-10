# Backup & Disaster Recovery Plan

Status: `[UNKNOWN]` for actual backup configuration — this is an
account/console-level setting on Neon (database) and, to a lesser
extent, Render/Vercel (stateless compute + uploaded-file storage) that
this codebase cannot verify by reading source code. This document
states what is knowable, what isn't, and what would need to happen to
turn `[UNKNOWN]` into `[PASS]` or `[FAIL]`.

## Database (Neon)

Neon offers point-in-time recovery (PITR) as a platform feature on most
plans, with a retention window that depends on the specific plan tier
provisioned for this project. **This has not been confirmed against
the actual Neon project settings as part of this round** — engineering
does not have console access exercised for this specific check.
`[UNKNOWN]`. Do not claim backups exist or work merely because Neon
generally offers the feature — the actual plan tier and retention
window must be confirmed, and per the user's own instruction, a real
non-production restore test is the only way to responsibly claim
"backups work."

### Recommended verification (not performed this round)

1. Confirm, via the Neon console, the project's actual plan tier and
   PITR retention window.
2. Create (or use, if one already exists) a Neon **branch** — Neon's
   branching feature can create a point-in-time branch of the database
   without touching production — and verify a specific known row (e.g.
   a synthetic test patient created for this exact purpose) is present
   and correct in the branch.
3. Document the actual retention window and the exact steps to restore,
   as a real runbook, not a generic statement that "Neon has backups."

None of steps 1–3 has been executed as part of this round —
`[EXTERNAL ACTION]` (requires Neon console access this task was not
exercised against) combined with `[UNKNOWN]` for the underlying
configuration.

## File storage (uploaded documents)

Uploaded files are stored on **local disk** on the Render backend
instance (`UPLOAD_DIR`), not in a separately-backed-up object store
(e.g. S3 with versioning). This is a real, distinct risk from the
database backup question: **a Render instance disk is not guaranteed
durable/backed-up the way a managed database is** — if the instance is
recreated (redeploy, instance migration, disk failure), locally-stored
files could be lost even if the database (which still has the
`documents.saved_to` path reference) survives. This has not been
verified against Render's actual disk-persistence guarantees for the
specific service plan in use. `[UNKNOWN]`, and worth calling out as
higher-priority than it might first appear: **this is a bigger gap than
the database backup question**, since database backups are at least a
standard managed-service feature, while durable file storage for
uploads is not confirmed to exist at all.

### Recommended remediation (not implemented)

Move uploaded-file storage to a managed, versioned object store (e.g.
S3-compatible storage with versioning/lifecycle rules) rather than
local disk. This is a real architecture change — file paths, upload
handlers, and the file-serving route (`/documents/{id}/file`) would all
need updating — not a safe drive-by change for this round, but flagged
as a priority follow-up given the durability gap identified above.

## Recovery time / recovery point objectives

Not yet defined — `[UNKNOWN]`. Defining RTO/RPO targets is a product/
business decision informed by the above technical facts, not something
engineering can set unilaterally without that input.

## Status summary

- Database backup existence: `[UNKNOWN]`.
- Database restore capability, verified: `[UNKNOWN]` — no restore test
  performed.
- Uploaded-file durability: `[UNKNOWN]`, with a documented reason to
  suspect it is weaker than the database's.
- RTO/RPO: `[UNKNOWN]`, needs a business decision.

Nothing in this section may be upgraded to `[PASS]` without the actual
verification steps above being performed and their results recorded
here.
