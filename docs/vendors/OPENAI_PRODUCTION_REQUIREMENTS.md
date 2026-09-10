# OpenAI Production Requirements

What OpenAI actually receives from this application (verified by
reading the code, not inferred), and what would need to be true
contractually before that can be called acceptable for health data.

## What is sent, exactly

1. **Page-extraction fallback** (`backend/app/ai_extract.py`): a
   **full-page rendered PNG image** of the uploaded document (base64
   data URL, `line 48-49`), plus up to **12,000 characters of raw OCR
   text** (`line 247`, `ocr_text[:12000]`) in the prompt. This path
   explicitly asks the model to extract `patient_name`, DOB, and other
   identity fields as structured output — i.e., it is designed to
   process direct identifiers, not just de-identified clinical values.
2. **Discharge-summary extraction** (`app/services/discharge_summary_pipeline.py`,
   lines ~255–280): base64-encoded **page images** sent as
   `image_url` data URLs — potentially the entire multi-page document,
   depending on how many pages the discharge summary has.

No redaction, de-identification, or field-level minimization happens
before either call — the full page content (image + OCR text) goes to
OpenAI's API as-is.

## What OpenAI's own terms would need to establish

`[EXTERNAL ACTION]`/`[LEGAL REVIEW]` — not verifiable from this
codebase:

1. **Zero Data Retention (ZDR)** or an equivalent agreement — whether
   OpenAI retains submitted content (images, OCR text, prompts) for
   model improvement or any purpose beyond serving the immediate API
   response, and for how long. OpenAI's standard API terms differ from
   ChatGPT consumer terms; the applicable terms for the API product
   used here need confirming, along with whether a ZDR add-on is
   active on this account.
2. **A signed DPA** covering the processing of EU personal data
   (this system's patient population is implied to be Romanian/EU,
   given CNP usage) and, specifically, special-category health data
   under GDPR Art.9 — a standard commercial DPA does not automatically
   cover Art.9 data without explicit terms.
3. **Data residency / international transfer mechanism** — where
   OpenAI processes this data geographically, and what transfer
   safeguard (SCCs, adequacy decision, etc.) applies if it leaves the
   EU/EEA. See `docs/privacy/TRANSFER_REGISTER.md`.
4. **Model training opt-out confirmation** — whether API-submitted
   content is used to train OpenAI's models by default, and whether
   this account has opted out (API usage is generally NOT used for
   training by default per OpenAI's public API terms, but this has not
   been independently confirmed against this specific account's actual
   settings/agreement).

## Engineering-side requirements not yet met

- No documented, user-facing consent specifically naming OpenAI as a
  sub-processor of uploaded document content (see
  `docs/privacy/PROCESSING_PURPOSES.md`'s gap note).
- No data-minimization step before either OpenAI call (§"What is sent"
  above) — sending the full page image plus up to 12,000 chars of OCR
  text, including identity fields, is more than the extraction task
  strictly requires and is flagged as a real (not paperwork) gap in
  `BRAGI_SECURITY_GDPR_PLAN.md` §21.
- No confirmation of what OpenAI API tier/agreement this account is
  actually on.

## Status

`[FAIL]` for data minimization to this vendor. `[UNKNOWN]`/`[LEGAL
REVIEW]`/`[EXTERNAL ACTION]` for every contractual/DPA/ZDR item above —
none can be resolved by engineering alone.
