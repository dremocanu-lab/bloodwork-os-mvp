# OpenAPI Equivalence Report — Phase 4 Backend Modularization

This report compares the API contract at the very start of Phase 4
(commit `bfbc570`, captured in `tests/contracts/openapi_pre_modularization.json`
and `tests/contracts/route_inventory_pre_modularization.json`) against
the contract after all 14 domains were extracted (final commit on
`refactor/backend-modularization` before merge).

## Method

After every single commit in this phase (14 domain extractions plus the
safety-harness commit), the same two checks were run and their results
recorded in that commit's message:

1. **Full OpenAPI document comparison** — `app.openapi()` regenerated
   from the current code, compared key-for-key (`==` on the parsed JSON,
   sorted keys) against the baseline snapshot.
2. **Route inventory comparison** — a custom extractor
   (`tests/contracts/generate_route_inventory.py`) that walks
   `app.routes` and records path, HTTP methods, route name, tags, and
   every dependency's real identity — including recovering
   `require_role(...)`'s actual allowed-roles tuple from its closure,
   not just the generic `dependency` function object — compared
   entry-for-entry against the baseline.

## Result

**Zero unexplained differences.** Every one of the 14 domain-extraction
commits, plus the two mechanical cleanup edits made along the way
(dropping now-unused imports; removing four dead duplicate Pydantic
classes left behind after the documents.py extraction), produced an
OpenAPI document and route inventory **byte-for-byte identical** to the
pre-modularization baseline.

| Check | Before | After | Diff |
|---|---|---|---|
| Total routes (`app.routes` with an HTTP method) | 117 | 117 | 0 |
| OpenAPI paths | 99 | 99 | 0 |
| OpenAPI document (full, sorted-key JSON equality) | — | — | **identical** |
| Route inventory (path/methods/name/tags/dependencies) | — | — | **identical** |

No route's URL, HTTP method, request schema, response schema,
status-code semantics, tags, or authorization dependency changed at any
point in this phase. The one path/route-count fluctuation that arose
during work-in-progress (an interim `tags=["interop"]` on the very first
router extraction, which produced a cosmetic `tags: []` → `tags:
['interop']` diff) was caught immediately and reverted before that
commit was finalized — the merged history contains no commit with a
non-empty diff.

## What "equivalence" was checked against, precisely

- **Path**: every route's URL template, including path parameters,
  unchanged.
- **Method**: GET/POST/PUT/DELETE/PATCH per route, unchanged.
- **Request/response schema**: every Pydantic model's field set,
  types, `Optional`/default semantics, and JSON Schema shape, unchanged
  (routes moved with their request/response models moved alongside
  them, verbatim).
- **Authorization dependency**: `generate_route_inventory.py`
  specifically decodes `require_role(...)`'s closure to recover the
  actual allowed-roles tuple (e.g. `require_role('admin',)`), not just
  "some dependency object" — so a route silently changing from
  `require_role("doctor", "admin")` to `require_role("admin")`, or vice
  versa, would have shown up as a route-inventory diff. None did.
- **Tags**: preserved exactly (empty on every route both before and
  after, per the original codebase's convention of not using FastAPI
  tags).

## Domains covered (in extraction order)

interop, root/ops, labs/bloodwork-trends, patient-events, medications,
assignments/access-requests, care-partner-settings, admin,
source-evidence, documents/uploads, patients (core/PCP/search) +
account (delete/export/profile), emergency (break-glass), Ask Bragi,
auth.

## Conclusion

The API contract exposed to the frontend and any external client is
unchanged. Every difference that was ever produced during this phase
was caught by the same-commit verification step before that commit was
considered done, and none survived into the final state. Target of
"zero unexplained differences" — met.
