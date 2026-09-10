# Reducto Production Requirements

What Reducto actually receives from this application, and what would
need to be true contractually before that can be called acceptable for
health data.

## What is sent, exactly

`app/services/reducto_client.py` sends requests to
`https://platform.reducto.ai` for classify, split, parse, and extract
operations. All four operate on the **full original uploaded file** —
there is no pre-processing/redaction/field-stripping step before the
file reaches Reducto. This is the primary document-processing vendor
for this application (the OpenAI path is described as a fallback in
this codebase's own naming/comments) — the majority of uploaded
documents' content passes through Reducto, not around it.

`REDUCTO_TIMING` log lines (an existing, pre-this-round convention)
were confirmed PHI-free by design — they log timing/status, not
content — which is a real, already-correct piece of minimization at
the *logging* layer, distinct from the *vendor-transmission* question
addressed here.

## What Reducto's own terms would need to establish

`[EXTERNAL ACTION]`/`[LEGAL REVIEW]` — not verifiable from this
codebase:

1. **A signed DPA/BAA-equivalent** covering health data processing —
   Reducto is a document-AI platform vendor; whether its standard
   commercial terms extend to Art.9 special-category health data (or a
   HIPAA-equivalent BAA, if any US-healthcare-adjacent use ever
   applies) needs explicit confirmation.
2. **Data retention policy** — how long Reducto retains submitted
   documents/extraction results after processing, and whether deletion
   can be requested/verified.
3. **Data residency / transfer mechanism** for any EU personal data
   processed outside the EU/EEA. See `docs/privacy/TRANSFER_REGISTER.md`.
4. **Sub-processor list** — whether Reducto itself uses further
   sub-processors (e.g. its own underlying model providers) that would
   need to be reflected in `docs/privacy/VENDOR_REGISTER.md`.

## Engineering-side requirements not yet met

- No documented, user-facing consent specifically naming Reducto as a
  sub-processor of uploaded document content.
- No data-minimization step before sending the full file — every
  upload's complete content (not just the fields ultimately needed)
  goes to Reducto by design, since classify/split/parse genuinely need
  the whole document to do their job (unlike the OpenAI fallback path,
  where sending the full page image is more avoidable). This is a more
  defensible design than the OpenAI path for that reason, but the
  vendor-terms gaps above still apply equally.

## Status

`[UNKNOWN]`/`[LEGAL REVIEW]`/`[EXTERNAL ACTION]` for every contractual
item above — none can be resolved by engineering alone. Technical
integration itself (auth via `REDUCTO_API_KEY`, error handling,
non-retryable auth-failure classification) is `[PASS]` — confirmed by
code review of `reducto_client.py`'s existing, already-hardened error
handling.
