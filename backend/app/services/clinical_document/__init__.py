"""Clinical Document Intelligence (V3 contract) — the clinical
normalization/canonicalization/provenance layer that sits ON TOP of
provider/OCR extraction (Reducto, Google Document AI, OpenAI-vision),
never replacing it and never re-parsing raw files itself. See
`docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md` for the
full contract and phase plan; `docs/clinical_document_v3/
CURRENT_PIPELINE_MAP.md` for how the pre-existing ingestion pipeline
works today.

Phase 3 (this package's starting point) defines the typed, versioned
`StructuredClinicalDocument` schema — see `schema.py` — and how it is
persisted/read through the existing `Document.note_body` field — see
`persistence.py`. No parser exists yet; that is Phase 4+.
"""
