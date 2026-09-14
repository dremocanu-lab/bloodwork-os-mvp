"""Typed, versioned structured clinical-document schema — Clinical
Document Intelligence V3, Phase 3.

This is the ONE typed contract every later phase (discharge parser,
Clinical Course event extraction, embedded lab/medication extraction,
the discharge reader frontend, Ask Bragi's structured retrieval) reads
and writes against. No phase after this one should invent its own
ad-hoc JSON shape for "structured document content" — see
`docs/handoffs/CLINICAL_DOCUMENT_INTELLIGENCE_V3_HANDOFF.md`'s "Hard
constraints" section.

Design notes (see the V3 contract for the full rules these encode):

- `sections` never devolves into "title + one giant text string" — see
  the typed `ClinicalBlock` union below. Free text that can't be
  confidently structured stays a `ParagraphBlock`, not a reason to skip
  structure entirely.
- Blocks that reference labs/medications/dated-events store IDS
  (`lab_result_ids`, `medication_ids`, `event_ids`), never a copy of
  that data — the canonical tables (`LabResult`, `PatientMedication`,
  this schema's own `dated_events`) remain the single source of truth.
  A block is a pointer, never a second datastore.
- `canonical_key` is a fixed, closed enum (`CanonicalSectionKey` below)
  — never the raw source heading. Two sections that map to the same
  canonical key are NOT valid as two separate entries in one document
  (`_canonical_keys_are_unique`, below) — a parser MUST merge them
  before constructing this model, preserving each original heading in
  `source_headings` and each blob of text as its own block, in order.
- Nothing here is ever silently "corrected." A suspicious/implausible
  source value is represented as-is (in a block's own text/fields) plus
  a `WarningBlock` or a document-level `warnings` entry — this schema
  has no field whose job is to hold a "fixed" version of a source fact.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union, get_args

from pydantic import BaseModel, Field, model_validator

from app.services.document_taxonomy import DocumentType

# Bumped only when a change to this schema would make an OLDER persisted
# payload fail validation if read with the newer models (i.e. a real
# breaking change) — additive, backward-compatible fields do not require
# a bump. See persistence.py for how an unrecognized/older version is
# handled on read.
CURRENT_SCHEMA_VERSION = "v1"

CanonicalSectionKey = Literal[
    "overview",
    "administrative_information",
    "encounter_details",
    "diagnoses",
    "medical_history",
    "examination",
    "clinical_course",
    "investigations",
    "laboratory_results",
    "imaging",
    "procedures",
    "treatment",
    "medications",
    "discharge_medications",
    "recommendations",
    "follow_up",
    "prescriptions",
    "signatures",
    "other",
]

# For runtime validation/error messages and for anything that needs to
# iterate the fixed set (e.g. a future canonical-heading classifier's
# own tests) without re-typing the literal list a second time.
CANONICAL_SECTION_KEYS: tuple[str, ...] = get_args(CanonicalSectionKey)


# ── Typed block forms ────────────────────────────────────────────────────
# Every block carries its own `type` discriminator so a document can be
# deserialized back into the exact block subtype it was written as
# (Pydantic discriminated union — see `ClinicalBlock` below), not a
# generic dict a reader has to re-sniff.


class ParagraphBlock(BaseModel):
    """Unstructured prose, kept verbatim — the honest fallback when
    structure can't be confidently established. Never the ONLY block
    type a real parser is allowed to produce for everything; see this
    module's own docstring."""

    type: Literal["paragraph"] = "paragraph"
    text: str


class KeyValueItem(BaseModel):
    key: str
    value: str


class KeyValueBlock(BaseModel):
    type: Literal["key_value"] = "key_value"
    items: list[KeyValueItem] = Field(default_factory=list)


class BulletListBlock(BaseModel):
    type: Literal["bullet_list"] = "bullet_list"
    items: list[str] = Field(default_factory=list)


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class DatedEventGroupBlock(BaseModel):
    """References `StructuredClinicalDocument.dated_events[].source_event_id`
    — never a copy of an event's own data. Exactly one place
    (`dated_events`) owns what an event actually says (Phase 5)."""

    type: Literal["dated_event_group"] = "dated_event_group"
    event_ids: list[str] = Field(default_factory=list)


class LabReportReferenceBlock(BaseModel):
    """References real `LabResult.id` values (Phase 6) — a pointer into
    the existing canonical lab table, never a second lab datastore."""

    type: Literal["lab_report_reference"] = "lab_report_reference"
    lab_result_ids: list[int] = Field(default_factory=list)


class MedicationListBlock(BaseModel):
    """References real `PatientMedication.id` values (Phase 7) — same
    pointer-not-copy rule as `LabReportReferenceBlock`."""

    type: Literal["medication_list"] = "medication_list"
    medication_ids: list[int] = Field(default_factory=list)


class PrescriptionRow(BaseModel):
    """One line of a prescriptions table. `medication_id` is populated
    once Phase 7's extraction resolves this row against
    `PatientMedication` — null until then, never fabricated."""

    drug_text: str
    dose_text: str | None = None
    medication_id: int | None = None


class PrescriptionTableBlock(BaseModel):
    type: Literal["prescription_table"] = "prescription_table"
    rows: list[PrescriptionRow] = Field(default_factory=list)


class WarningBlock(BaseModel):
    """An in-place flag for a suspicious/implausible source value (e.g.
    "AV 1008 bpm") — the value itself stays exactly as written, in
    whichever other block carries it; this block never holds a
    'corrected' value, only the warning text and, where known, the
    SourceEvidence this concerns."""

    type: Literal["warning"] = "warning"
    message: str
    source_evidence_ids: list[int] = Field(default_factory=list)


ClinicalBlock = Annotated[
    Union[
        ParagraphBlock,
        KeyValueBlock,
        BulletListBlock,
        TableBlock,
        DatedEventGroupBlock,
        LabReportReferenceBlock,
        MedicationListBlock,
        PrescriptionTableBlock,
        WarningBlock,
    ],
    Field(discriminator="type"),
]


class ClinicalSection(BaseModel):
    """One canonical section of a structured clinical document. Multiple
    raw source headings can and often do fold into one of these (e.g.
    several "EPICRIZĂ" pages) — `source_headings` preserves every
    original heading text that contributed, `blocks` preserves each
    contributor's own content as separate ordered blocks (never
    concatenated into one opaque string)."""

    id: str
    canonical_key: CanonicalSectionKey
    display_title: str
    source_headings: list[str] = Field(default_factory=list)
    order: int
    blocks: list[ClinicalBlock] = Field(default_factory=list)
    # Real SourceEvidence ids this section's content is grounded in —
    # empty until a real parser (Phase 4+) populates it; never fabricated.
    source_evidence_ids: list[int] = Field(default_factory=list)
    confidence: float | None = None
    review_state: Literal["auto", "needs_review", "reviewed"] | None = None


EventType = Literal[
    "admission",
    "follow_up",
    "procedure",
    "treatment_change",
    "investigation",
    "discharge",
    "consultation",
    "other",
]


class ClinicalEvent(BaseModel):
    """One dated event inside the clinical course (Phase 5). `raw_date_text`
    and `raw_text` are always the verbatim source — `normalized_date`/
    `date_confidence` are Bragi's own interpretation ON TOP of that, never
    a replacement for it. A suspicious date is never silently repaired:
    it is preserved in `raw_date_text`, `normalized_date` is left null or
    marked with a low `date_confidence`, and a note is added to
    `warnings` — see the V3 contract's "NEVER silently repair" rule."""

    source_event_id: str
    raw_date_text: str
    normalized_date: str | None = None
    date_confidence: float = 0.0
    event_type: EventType
    raw_text: str
    structured_observations: list[str] = Field(default_factory=list)
    medication_changes: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    source_evidence_ids: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DerivedArtifactRef(BaseModel):
    """A pointer to a derived artifact (Phase 6's derived lab report,
    today the only kind) built FROM this document — never a second copy
    of that artifact's data. `document_id` is the derived artifact's own
    `Document.id` once Phase 6 actually creates one; null here at
    Phase 3, since no parser/derivation exists yet."""

    artifact_type: Literal["lab_report"] = "lab_report"
    document_id: int | None = None
    source_section_id: str | None = None
    lab_result_ids: list[int] = Field(default_factory=list)


class DocumentMetadata(BaseModel):
    """Identity/encounter metadata already extractable today (see
    discharge_summary_pipeline.py's existing payload, which this
    supersedes) — never patient-identifying fields beyond what the
    existing pipeline already captured (no CNP here; CNP handling stays
    exactly where it already is on `Document`, per the app's existing
    minimization posture)."""

    patient_name: str | None = None
    date_of_birth: str | None = None
    sex: str | None = None
    admission_date: str | None = None
    discharge_date: str | None = None
    # Not a real `Document` column today (see CURRENT_PIPELINE_MAP.md
    # OPEN QUESTION #2) — carried here instead of being lost, same as it
    # already was inside the legacy note_body JSON blob.
    hospital_name: str | None = None
    department: str | None = None
    referring_doctor: str | None = None


class StructuredClinicalDocument(BaseModel):
    """The root schema. Persisted through `Document.note_body` — see
    `persistence.py`. Never partially trusted: any code that reads or
    writes one goes through `persistence.py`'s functions, which always
    construct/validate a real `StructuredClinicalDocument` instance
    rather than passing an unvalidated dict around."""

    schema_version: str = CURRENT_SCHEMA_VERSION
    parser_version: str
    document_kind: DocumentType
    source_language: str | None = None
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    sections: list[ClinicalSection] = Field(default_factory=list)
    dated_events: list[ClinicalEvent] = Field(default_factory=list)
    derived_artifacts: list[DerivedArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}  # no arbitrary unvalidated fields pass through

    @model_validator(mode="after")
    def _canonical_keys_are_unique(self) -> "StructuredClinicalDocument":
        seen: set[str] = set()
        dupes: set[str] = set()
        for section in self.sections:
            if section.canonical_key in seen:
                dupes.add(section.canonical_key)
            seen.add(section.canonical_key)
        if dupes:
            raise ValueError(
                f"Duplicate canonical_key(s) in sections: {sorted(dupes)!r} — "
                "repeated source headings (e.g. multiple EPICRIZĂ pages) must "
                "be merged into ONE canonical section before this model is "
                "constructed, preserving every original heading in "
                "source_headings and every contributor's text as its own "
                "block — see the V3 contract's canonical-heading rule."
            )
        return self

    @model_validator(mode="after")
    def _section_ids_are_unique(self) -> "StructuredClinicalDocument":
        ids = [section.id for section in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("ClinicalSection.id must be unique within a document.")
        return self

    @model_validator(mode="after")
    def _event_ids_are_unique(self) -> "StructuredClinicalDocument":
        ids = [event.source_event_id for event in self.dated_events]
        if len(ids) != len(set(ids)):
            raise ValueError("ClinicalEvent.source_event_id must be unique within a document.")
        return self
