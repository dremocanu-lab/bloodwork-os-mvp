# CNP / Identifier Encryption Plan

Status: assessment + design only. **No encryption-at-rest for CNP or
any other identifier has been implemented this round**, per the
explicit instruction governing this task: never migrate production
encryption impulsively, never invent custom cryptography, never store
keys alongside ciphertext.

## Current state

`patients.cnp` and `documents.cnp` are stored as plaintext `String`
columns (`backend/app/models.py`). CNP (Romania's national ID number)
is used as a real, active search/lookup key on
`GET /emergency/search?type=cnp&q=...` (`patients.cnp` is indexed for
exactly this query); `/patients/search` and `/admin/patients/search`
search by name/identifier/code, not CNP, but both return the unmasked
`cnp` field on every matched patient. Protection today is access
control (every route that returns it requires authentication +
authorization) and TLS in transit, not encryption at rest.

## Why this isn't just "add pgcrypto and go"

1. **CNP is used as an equality-searchable key.** Standard
   application-level encryption (AES-GCM with a random IV per row) makes
   equality search on the encrypted column impossible without decrypting
   every row — which would either require a deterministic-encryption
   scheme (weaker: allows correlation of identical values) or moving the
   search key to a separate, purpose-built lookup structure (e.g. a
   blind-index / HMAC column used only for exact-match lookup,
   alongside a separately-encrypted display value). This is a real
   design decision with real trade-offs, not a mechanical migration.
2. **Key management does not exist yet.** There is no KMS integration,
   no key-rotation mechanism, and no existing pattern in this codebase
   for handling encryption keys — introducing one is a genuine new piece
   of infrastructure (see `docs/security/KEY_ROTATION_RUNBOOK.md` for
   what a rotation plan would need once a KMS exists). Storing a key in
   an env var alongside `DATABASE_URL` on the same Render service would
   defeat much of the purpose (anyone who can read the app's env can
   read the key) — a real KMS (e.g. cloud provider KMS, or at minimum a
   key stored and rotatable independently of the app's own deploy
   environment) is a prerequisite, and provisioning one is
   `[EXTERNAL ACTION]`.
3. **A production migration of an indexed, actively-queried column used
   by live emergency-search workflows is high-blast-radius** — done
   wrong, it could break emergency patient lookup, which is a genuine
   patient-safety concern, not just a data-integrity one. This plan
   explicitly refuses to attempt that migration without first proving
   the approach safe in the dev DB, including a rollback plan.

## Recommended approach (not yet implemented)

1. Add a `cnp_lookup_hash` column (HMAC-SHA256 with a dedicated,
   KMS-managed key, not the JWT `SECRET_KEY`) for exact-match search,
   computed alongside the existing plaintext during a transition period
   — never derived from a weak/guessable input alone (CNP has a known
   structure, so an unsalted hash would be brute-forceable; use HMAC
   with a secret key, not a bare hash).
2. Add an encrypted-at-rest `cnp_encrypted` column (application-level
   AES-GCM, random nonce per value, key from the KMS) for display/
   retrieval; keep the plaintext `cnp` column until the migration is
   proven end-to-end in dev, then drop it in a separate, later step —
   never a single irreversible cutover.
3. Update every read/write path (`patients.cnp`, `documents.cnp`,
   `/emergency/search`, `/patients/search`, admin patient views) to use
   the new columns; add regression tests for search-by-CNP correctness
   before removing plaintext.
4. Only after dev-environment end-to-end verification (search still
   works, no plaintext CNP left in any response that doesn't need it,
   performance is acceptable) would a production rollout even be
   considered — and it would need a coordinated, reversible migration
   plan, not a single commit.

## Status

`[IMPLEMENTED — NOT DEPLOYED]` does not apply — nothing has been built
yet. Correctly `[FAIL]` for "CNP encrypted at rest," with the above as
the intended remediation path, gated on KMS provisioning
(`[EXTERNAL ACTION]`) before engineering can proceed further.
