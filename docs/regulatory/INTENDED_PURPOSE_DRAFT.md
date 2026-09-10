# Intended Purpose Statement — DRAFT (MDR / EU AI Act boundary)

`[LEGAL REVIEW]` required. This document uses deliberately conservative
language throughout. **It does not state that Bragi is definitively
outside the scope of the EU Medical Device Regulation (MDR) or the EU
AI Act, and it does not claim any certification under either.** Both
of those are legal/regulatory determinations this codebase cannot make.

## What Bragi does, as implemented today (factual, code-verified)

- Stores and displays medical documents a patient uploads.
- Extracts structured data (lab values, medications, dates) from those
  documents using OCR/AI vendors, always presented with a source
  citation back to the original document.
- Organizes extracted data into charts/timelines for the patient's and
  authorized clinicians' own review.
- Does **not** generate a diagnosis, a treatment recommendation, a risk
  score, or any other output that itself constitutes a clinical
  judgment — confirmed by code review: every AI/extraction code path
  produces *extracted values with provenance*, never an assessment,
  interpretation, or recommendation.
- Does **not** currently include an AI chat feature ("Ask Bragi") —
  confirmed absent from the codebase.

## Why this matters for MDR / EU AI Act scoping — questions, not answers

Whether software that organizes and displays a patient's own medical
data (without generating a diagnosis or recommendation) falls under
MDR's definition of a "medical device" (which turns on intended
purpose, including whether the software is intended for diagnosis,
prevention, monitoring, treatment, or alleviation of disease) is a
legal question that depends on:

1. The platform's own stated intended purpose (marketing materials,
   terms of service) — not solely on the current code's behavior.
   Regulatory classification looks at intended use as represented to
   users, not just technical function.
2. Whether any future feature (e.g. an AI chat feature that answers
   clinical questions, or a feature that flags "abnormal" values with
   any interpretive framing beyond a lab's own reference range) would
   change that classification — this is precisely why §2 of
   `docs/ai/AI_GOVERNANCE.md`'s forward-looking requirements exist:
   to keep engineering aware that adding interpretive/diagnostic
   framing to AI output is a regulatory-classification decision, not
   merely a product one.
3. Similarly, the EU AI Act's classification of "high-risk" AI systems
   in healthcare contexts depends on intended purpose and the specific
   function performed, not simply on "AI is used somewhere in the
   product."

## What engineering commits to, going forward

- Continue presenting all AI/OCR-extracted data as extracted evidence
  with source citation, never as an interpretation, diagnosis, or
  recommendation, unless and until a deliberate, legally-reviewed
  product decision changes that scope.
- Flag any future feature that adds interpretive/diagnostic framing
  (including AI chat responses that go beyond "here is what your
  document says") for regulatory review before shipping it, not after.
- Never state in user-facing copy, marketing, or documentation that
  Bragi is "not a medical device," "does not require MDR
  classification," or "is EU-AI-Act compliant" without that
  determination coming from actual legal/regulatory review.

## Status

`[LEGAL REVIEW]` — this document records engineering's understanding
of the current factual boundary and its own forward commitments; it is
not itself a regulatory determination.
