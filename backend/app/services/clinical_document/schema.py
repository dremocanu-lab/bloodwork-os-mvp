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


# Clinical Reader Intelligence V2. Whether a section/event belongs to the
# CURRENT encounter being discharged, or to historical narrative embedded
# in the same document (e.g. a decade of prior hematology follow-up
# inside one long "clinical_course"/"medical_history" section).
# "unspecified" is the honest default when the interpreter never ran or
# couldn't confidently tell — never guessed as "current" by default (a
# document with no scope information should read exactly as it did
# before this field existed).
EncounterScope = Literal["current", "historical", "unspecified"]


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
    # Stable ids of every raw SourceSegment (see segments.py) that
    # contributed to this canonical section, in encounter order —
    # additive field (default empty list, so older persisted payloads
    # without it still validate). This is what lets a later phase (labs,
    # medications, prescriptions, Ask Bragi citations) point back to the
    # EXACT originating segment rather than only a heading string.
    source_segment_ids: list[str] = Field(default_factory=list)
    order: int
    blocks: list[ClinicalBlock] = Field(default_factory=list)
    # Real SourceEvidence ids this section's content is grounded in —
    # empty until a real parser (Phase 4+) populates it; never fabricated.
    source_evidence_ids: list[int] = Field(default_factory=list)
    confidence: float | None = None
    review_state: Literal["auto", "needs_review", "reviewed"] | None = None
    # Clinical Reader Intelligence V2 — additive, default None (older
    # payloads/sections the interpreter never scored render exactly as
    # before). Only the AI interpreter (ai_interpreter.py) sets this,
    # never a deterministic parser guess.
    encounter_scope: EncounterScope | None = None
    # A deterministic (non-AI) signal: this section's only real content is
    # a form template with no patient-specific values (e.g. "PRODUS /
    # CANTITATE" headers with nothing filled in) — see
    # template_detection.py. The reader suppresses a section flagged this
    # way from the intelligent-reader view, but NEVER deletes it — it
    # remains visible in Original/Full source narrative mode.
    is_template_only: bool = False


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
    # Clinical Reader Intelligence V2 — same meaning/defaults as
    # ClinicalSection.encounter_scope, set only by the AI interpreter.
    encounter_scope: EncounterScope | None = None
    # True when this event's raw_text is judged (conservatively, by the
    # interpreter) to be a near-duplicate of another event already in
    # this document — PRESENTATION consolidation only. The event row
    # itself, and every source reference, is NEVER deleted; the reader
    # may choose not to render a second card for it, showing "Repeated in
    # source" instead. Default False.
    is_repeated_in_source: bool = False


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
    # Phase 6's deterministic coherent-report identity (see
    # lab_grouping.py's `LabReportGroup.group_key`) — additive, defaults
    # to None for anything built before Phase 6. Distinguishes MULTIPLE
    # derived artifacts that share the same `source_section_id` (a
    # laboratory_results section containing more than one coherent
    # report) and is what makes derived-artifact get-or-create
    # idempotent across repeated ingestion of the same document.
    group_key: str | None = None


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


DiagnosisRole = Literal["principal", "secondary", "historical"]


class Diagnosis(BaseModel):
    """A real diagnosis concept, grounded in source — never an AI
    translation/normalization of the wording (source text is
    authoritative; see the V3/V2 contract's "source wording remains
    authoritative" rule — a coded terminology layer may be ADDED later,
    never substituted for `text`). A blank/placeholder diagnosis field
    (e.g. an empty "DIAGNOSTIC SECUNDAR" line) is never represented as a
    Diagnosis at all — absence here means absence, not "none" text."""

    id: str
    code: str | None = None
    text: str
    role: DiagnosisRole
    source_section_id: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[int] = Field(default_factory=list)


InvestigationType = Literal["imaging", "molecular", "pathology", "ecg", "procedure", "other"]


class Investigation(BaseModel):
    """A real investigation FINDING, whether it came from an explicit
    form field or was recognized inside narrative prose (e.g. "JAK2
    V617F" mentioned mid-paragraph). `findings`/`conclusion` are only
    ever populated from what the source itself states — the interpreter
    never invents a conclusion the source doesn't give."""

    id: str
    investigation_type: InvestigationType
    title: str
    findings: str | None = None
    conclusion: str | None = None
    source_section_id: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[int] = Field(default_factory=list)


AnomalyType = Literal[
    "impossible_or_unusual_date",
    "physiologically_implausible_value",
    "conflicting_source_values",
    "repeated_source_text",
    "ocr_uncertain",
    "demographic_context_mismatch",
    "template_placeholder",
    "chronology_uncertain",
]


class AnomalyFlag(BaseModel):
    """A candidate source anomaly. `original_value` is ALWAYS the
    verbatim source value — this model has no field for a "corrected"
    value and never will; see the V2 contract's "AI may flag, AI may not
    correct" rule."""

    id: str
    anomaly_type: AnomalyType
    message: str
    original_value: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[int] = Field(default_factory=list)


RecommendationCategory = Literal[
    "activity", "hydration", "diet", "precautions", "follow_up", "medication_recommendation", "specialist_follow_up", "other"
]


class RecommendationItem(BaseModel):
    id: str
    category: RecommendationCategory
    text: str
    source_section_id: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[int] = Field(default_factory=list)


class TreatmentEra(BaseModel):
    """A semantic grouping of the longitudinal clinical course into a
    named era (e.g. "Hydrea + therapeutic phlebotomy period") — MUST be
    grounded in real dated_events; never a hard-coded/invented date
    range. `event_ids` are pointers into `dated_events`, same
    pointer-not-copy rule as every other block type in this schema."""

    id: str
    label: str
    start_date: str | None = None
    end_date: str | None = None
    description: str = ""
    event_ids: list[str] = Field(default_factory=list)


class CurrentEncounter(BaseModel):
    """A dedicated pointer to what makes up THIS encounter/hospitalization
    — never a copy of section/event data, just the ids that belong to it.
    Distinguishing this from historical narrative is Clinical Reader
    Intelligence V2's central product requirement."""

    admission_date: str | None = None
    discharge_date: str | None = None
    section_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)


class InterpretationMetadata(BaseModel):
    """Versioning/audit record for the AI Clinical Document Interpreter's
    pass over this document — see ai_interpreter.py. The reader must
    render deterministically from what's PERSISTED here; this metadata is
    what lets the UI show "Organized from source · Unverified" honestly,
    and what a later reprocessing pass compares against to decide whether
    to re-run."""

    schema_version: str = "v1"
    prompt_version: str
    model: str
    generated_at: str
    status: Literal["complete", "partial", "failed", "unavailable"]
    warnings: list[str] = Field(default_factory=list)


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

    # Clinical Reader Intelligence V2 — all additive, all default to an
    # empty/None "the interpreter never ran" state, so every payload
    # persisted before this field existed still validates unchanged.
    # Populated ONLY by ai_interpreter.py (never by a deterministic
    # parser) and validated server-side (see interpretation_validation.py)
    # before being allowed into this document at all — ungrounded/
    # hallucinated items are filtered out before construction, never
    # merely hidden by the frontend.
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    investigations: list[Investigation] = Field(default_factory=list)
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    treatment_eras: list[TreatmentEra] = Field(default_factory=list)
    current_encounter: CurrentEncounter | None = None
    interpretation: InterpretationMetadata | None = None

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
