# Data Protection Impact Assessment — DRAFT

`[LEGAL REVIEW]` required — a DPIA is a formal legal/compliance
exercise; this is an engineering-drafted input to that process, not a
completed or authoritative DPIA. Structured loosely on the standard
GDPR Art.35 DPIA elements.

## 1. Is a DPIA required?

Likely yes, pending legal confirmation: this system involves
large-scale processing of special-category health data (Art.9), used
in ways that could be considered "systematic and extensive" for the
patients who use it as their primary records tool, and includes a
novel AI-based extraction pipeline. `[LEGAL REVIEW]` for a final
determination against the applicable DPIA-trigger criteria.

## 2. Description of processing

See `docs/privacy/BRAGI_DATA_MAP.md` and
`docs/privacy/PROCESSING_PURPOSES.md` for the complete, code-verified
description. Summary: patients upload medical documents; three AI/OCR
vendors (Reducto, OpenAI, Google Document AI) extract structured data;
patients, authorized doctors, care partners, and (opt-in, time-boxed)
emergency workers can view the resulting records under role-based
access control.

## 3. Necessity and proportionality assessment

- **Is the data collected necessary for the stated purpose?**
  Substantially yes — the core function (structured medical records
  from uploaded documents) requires processing document content. The
  specific gap identified this round: sending the *entire* page image
  and up to 12,000 characters of raw OCR text to OpenAI's fallback path
  (`docs/vendors/OPENAI_PRODUCTION_REQUIREMENTS.md`) is broader than
  strictly necessary — a proportionality concern worth addressing via
  data minimization, not a fundamental necessity problem.
- **Is the retention period proportionate?** Cannot be assessed until
  `docs/privacy/RETENTION_POLICY.md`'s legal-review gap is resolved.
- **Is access appropriately limited?** Substantially yes — see
  `docs/security/AUTHORIZATION_MATRIX.md`, verified via a real IDOR
  regression suite this round. Two identified deviations (admin's
  blanket access, self-selected `role` at signup) are flagged as
  product decisions requiring confirmation, not silently accepted as
  fine.

## 4. Risk assessment

Cross-referenced against `docs/security/THREAT_MODEL.md`'s 19 scenarios.
Highest-residual-risk items for a DPIA's purposes specifically (risk
*to the data subject*, not just to the system):

1. **CNP exposure** (§4.11 of the threat model) — a national ID number
   is a high-impact identifier if exposed; currently protected by
   access control only, not encryption at rest, and appears in 2 URL
   query strings. Real, documented risk to data subjects.
2. **AI vendor data minimization gap** (§4.14) — broader-than-necessary
   data sent to OpenAI specifically; risk depends on OpenAI's actual
   retention/training terms, which are `[UNKNOWN]`.
3. **No malware scanning** (§4.9) — risk is primarily to system
   integrity/availability, secondarily to data subjects if a compromise
   led to broader data exposure.
4. **No rate limiting** (§4.2) — increases credential-stuffing risk to
   individual accounts.
5. **Uploaded-file durability gap** (`docs/security/BACKUP_DR_PLAN.md`)
   — risk of data loss (right to have accurate, available records),
   distinct from confidentiality risk.

## 5. Measures to address the risks

See `BRAGI_SECURITY_GDPR_PLAN.md` §24 (residual risks) for the complete,
prioritized list of what's already fixed this round versus what remains
open, with evidence for each closed item and a stated remediation path
for each open one. This DPIA draft does not duplicate that list —
it defers to it as the authoritative current-state record.

## 6. Consultation

`[LEGAL REVIEW]`/`[EXTERNAL ACTION]` — a real DPIA requires
consultation with a Data Protection Officer (if one is designated) and,
depending on the residual risk level found, potentially prior
consultation with the supervisory authority (Art.36) if risks cannot be
sufficiently mitigated. None of this has occurred; this draft is an
engineering input to that process, not a substitute for it.

## Status

This document must not be represented as a completed DPIA. It is a
structured, code-verified starting point for one.
