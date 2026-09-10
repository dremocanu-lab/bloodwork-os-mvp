# Privacy Notice — DRAFT (not published, not legally reviewed)

`[LEGAL REVIEW]` required before publication. This is an engineering-
drafted starting point based on the actual, verified data flows in
`docs/privacy/BRAGI_DATA_MAP.md` and `docs/privacy/PROCESSING_PURPOSES.md`
— not a template, and not ready to publish as-is. Placeholders are
marked `[PLACEHOLDER]`.

---

## Who we are

[PLACEHOLDER — legal entity name, registered address, and contact
details. Not filled in here deliberately: no hardcoded personal or
organizational contact information should appear in this repository
per this task's own rules — final values belong in the published
notice, sourced from whoever owns that decision, not invented here.]

## What data we collect

- **Account information**: your name and email address.
- **Health information**: the medical documents you upload, and the
  structured data (lab results, medications, clinical notes) we
  extract from them, including identifying information that may appear
  in those documents (such as your CNP/national ID, date of birth, and
  sex).
- **Access records**: who has viewed or been granted access to your
  records, and when (for your own accountability and security).
- **Emergency contacts**: if you choose to add them, the name, phone
  number, and relationship of people you'd like contacted in an
  emergency.

## Why we process it

See `docs/privacy/PROCESSING_PURPOSES.md` for the full breakdown. In
summary: to provide you the service you sign up for (viewing your own
records), to let clinicians you authorize view your records, to
extract structured data from documents you upload (using third-party
AI/document-processing services — see "Who we share it with" below),
and to maintain security/audit records.

## Who we share it with

Uploaded documents are processed by the following third parties to
extract structured data:

- **Reducto** (document classification and data extraction)
- **OpenAI** (fallback data extraction for some document types)
- **Google Cloud (Document AI)** (optical character recognition)

See `docs/privacy/VENDOR_REGISTER.md` for the complete list, including
infrastructure providers (database and hosting). [PLACEHOLDER — final
notice should link to or restate each vendor's own privacy
commitments once confirmed per `docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md`
and `docs/vendors/REDUCTO_PRODUCTION_REQUIREMENTS.md`.]

We do not sell your data or use it for advertising. No advertising or
marketing-analytics vendor receives your data — confirmed by code
review, not merely stated as policy.

## Your rights

You can access, correct, and delete your own data through your
account. See `docs/privacy/DSAR_RUNBOOK.md` for the current state of
each right's implementation — [PLACEHOLDER: do not publish a claim
about export/portability until the export feature referenced there
actually exists, or rephrase to describe the manual-request process
honestly].

## How long we keep your data

[PLACEHOLDER — pending `docs/privacy/RETENTION_POLICY.md`'s legal
review; do not publish a specific retention period until one is
legally confirmed.]

## Emergency access

If you enable "emergency discoverability," authorized emergency
personnel can request time-limited (30 minutes), audited access to
your records in an emergency. You can disable this at any time.

## Contact us

[PLACEHOLDER — a monitored contact channel, not an individual's
personal email, per `docs/security/PRODUCTION_ACCESS_POLICY.md`.]

---

**Engineering note (remove before publication)**: every factual claim
above was checked against the actual codebase this round. The
placeholders exist because the missing information is either a legal
determination, a business decision, or literally does not exist yet
(the export feature) — publishing this notice with the placeholders
unfilled, or with claims not yet true, would itself be a compliance
problem, not a solution to one.
