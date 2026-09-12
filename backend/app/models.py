from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base

# --- Additive columns for LabResult / Document -----------------------------
# Interoperability (see BRAGI_INTEROP_PLAN.md): a lab result or document that
# arrived via an external standards-based connector (FHIR, later HL7/CDA/
# DICOMweb) rather than a patient/doctor upload carries a `source_connection_id`
# pointing at the ConnectionProfile that produced it, and — for lab results —
# an `external_observation_id` (the partner's own resource id) used for
# idempotent re-sync (see app/services/interop/fhir_connector.py). Both are
# null for every existing row and for every ordinary upload; nothing about
# the upload pipeline changes.


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, index=True)
    department = Column(String, nullable=True)
    hospital_name = Column(String, nullable=True)
    doctor_type = Column(String, nullable=True)  # "pcp" | "specialist" | null
    # Soft-deletion marker for roles whose row must survive their own
    # account deletion (doctor/admin — clinical/audit records reference
    # them by id across many tables; see Priority 8 in
    # BRAGI_SECURITY_GDPR_PLAN.md). Null means active. get_current_user()
    # and login() both reject any user with this set, so a soft-deleted
    # account is functionally gone even though the row persists. Patient
    # and care_partner deletion remain real row deletes — see
    # DELETE /my/account.
    deleted_at = Column(String, nullable=True)

    uploaded_documents = relationship("Document", back_populates="uploaded_by_user")
    linked_patient = relationship("Patient", back_populates="linked_user", uselist=False)


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, nullable=True, unique=True, index=True)
    linked_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    full_name = Column(String, nullable=False, index=True)
    date_of_birth = Column(String, nullable=True)
    age = Column(String, nullable=True)
    sex = Column(String, nullable=True)
    cnp = Column(String, nullable=True, index=True)
    patient_identifier = Column(String, nullable=True, index=True)
    emergency_search_enabled = Column(Integer, nullable=False, default=0)
    emergency_search_updated_at = Column(String, nullable=True)
    emergency_search_consent_text_version = Column(String, nullable=True)

    linked_user = relationship("User", back_populates="linked_patient")
    documents = relationship("Document", back_populates="patient", foreign_keys="Document.patient_id")
    doctor_access_links = relationship("DoctorPatientAccess", back_populates="patient")
    access_requests = relationship("DoctorPatientAccessRequest", back_populates="patient")
    events = relationship("PatientEvent", back_populates="patient")
    medications = relationship("PatientMedication", back_populates="patient")
    emergency_contacts = relationship("EmergencyContact", back_populates="patient", order_by="EmergencyContact.id")


class DoctorPatientAccess(Base):
    __tablename__ = "doctor_patient_access"

    id = Column(Integer, primary_key=True, index=True)
    doctor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    granted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at = Column(String, nullable=False)
    is_active = Column(Integer, nullable=False, default=1, index=True)
    ended_at = Column(String, nullable=True)

    doctor_user = relationship("User", foreign_keys=[doctor_user_id])
    patient = relationship("Patient", back_populates="doctor_access_links")
    granted_by_user = relationship("User", foreign_keys=[granted_by_user_id])


class DoctorPatientAccessRequest(Base):
    __tablename__ = "doctor_patient_access_requests"

    id = Column(Integer, primary_key=True, index=True)
    doctor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    requested_at = Column(String, nullable=False)
    responded_at = Column(String, nullable=True)
    responded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    doctor_user = relationship("User", foreign_keys=[doctor_user_id])
    patient = relationship("Patient", back_populates="access_requests")
    requested_by_user = relationship("User", foreign_keys=[requested_by_user_id])
    responded_by_user = relationship("User", foreign_keys=[responded_by_user_id])


class PatientEvent(Base):
    __tablename__ = "patient_events"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    doctor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active", index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    hospital_name = Column(String, nullable=True)
    department = Column(String, nullable=True)
    admitted_at = Column(String, nullable=False)
    discharged_at = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    discharged_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    patient = relationship("Patient", back_populates="events")
    doctor_user = relationship("User", foreign_keys=[doctor_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    discharged_by_user = relationship("User", foreign_keys=[discharged_by_user_id])


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, nullable=True, unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    section = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    saved_to = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=True)

    patient_name = Column(String, nullable=True)
    date_of_birth = Column(String, nullable=True)
    age = Column(String, nullable=True)
    sex = Column(String, nullable=True)
    cnp = Column(String, nullable=True)
    patient_identifier = Column(String, nullable=True)

    lab_name = Column(String, nullable=True)
    sample_type = Column(String, nullable=True)
    referring_doctor = Column(String, nullable=True)
    report_name = Column(String, nullable=True)
    report_type = Column(String, nullable=True)
    source_language = Column(String, nullable=True)
    test_date = Column(String, nullable=True)
    collected_on = Column(String, nullable=True)
    reported_on = Column(String, nullable=True)
    registered_on = Column(String, nullable=True)
    generated_on = Column(String, nullable=True)

    note_body = Column(Text, nullable=True)

    # Bragi document taxonomy (see app.services.document_taxonomy). Additive
    # to `section`, which keeps driving existing routing/grouping — see
    # BRAGI_REDUCTO_PLAN.md Phase 1.
    document_type = Column(String, nullable=True, index=True)
    classification_status = Column(String, nullable=True)
    classification_confidence = Column(Float, nullable=True)
    classification_source = Column(String, nullable=True)

    # Phase 2 — identity/duplicate safety (see app.services.patient_identity,
    # app.services.file_hash). identity_status: matched | needs_confirmation |
    # mismatch | insufficient_identity. A "mismatch" document is quarantined:
    # patient_id is left NULL (so it never appears in any patient-scoped
    # query) and intended_patient_id records who it was uploaded for, for
    # review. review_status: null | "quarantined".
    file_sha256 = Column(String, nullable=True, index=True)
    identity_status = Column(String, nullable=True)
    review_status = Column(String, nullable=True, index=True)
    intended_patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)

    # Phase 4 — conservative structured extraction for document types with
    # no dedicated pipeline (imaging/operative/pathology/prescription/
    # medication_list/specialist_consultation). JSON-encoded
    # {language, sections: {key: text}} from
    # app.services.structured_reader_service; null/empty when extraction
    # was unavailable or found nothing — the Reader always falls back to
    # extracted_text.
    structured_sections = Column(Text, nullable=True)

    # Real Reducto Parse persistence: the full document read (page/bbox-
    # tagged blocks), stored once at upload time rather than re-parsed on
    # every open — JSON-encoded {blocks: [{type, page, bbox_x/y/width/
    # height, content, confidence}], provider, parser_version}. Null for
    # documents processed by the legacy pipeline or before this existed;
    # `extracted_text` (already on this model) is always the fallback.
    parsed_content = Column(Text, nullable=True)

    # Real Reducto Split integration: a single upload that Reducto Split
    # detected as containing multiple logical documents (e.g. one PDF with
    # labs + an imaging report + a discharge summary) is stored as one
    # parent Document (the original file, untouched) plus one child
    # Document per detected section. `saved_to` on a child still points at
    # the PARENT's file — a child is a page-range *view* of the same
    # source, never a separate copy — so "View original" always opens the
    # real original upload. page_range_start/end are 1-indexed, inclusive,
    # and refer to the ORIGINAL document's page numbers (not renumbered).
    parent_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    page_range_start = Column(Integer, nullable=True)
    page_range_end = Column(Integer, nullable=True)

    # NOTE: the live Postgres column is `boolean` (pre-existing schema drift
    # from this model's prior `Integer` declaration — discovered and fixed
    # during Phase 2 testing; no migration needed since the DB column was
    # already boolean, only this declaration was wrong).
    is_verified = Column(Boolean, nullable=False, default=False)
    verified_by = Column(String, nullable=True)
    verified_at = Column(String, nullable=True)
    last_edited_at = Column(String, nullable=True)
    created_at = Column(String, nullable=True)

    # Interoperability — null for every upload. Set only for the synthetic
    # "sync batch" Document a FHIR (or later HL7/CDA/DICOMweb) connector
    # creates to hang its LabResult rows off of; see
    # app/services/interop/fhir_connector.py's commit path. Never set by the
    # upload pipeline.
    source_connection_id = Column(Integer, ForeignKey("interop_connections.id", ondelete="SET NULL"), nullable=True, index=True)

    patient = relationship("Patient", back_populates="documents", foreign_keys=[patient_id])
    intended_patient = relationship("Patient", foreign_keys=[intended_patient_id])
    parent_document = relationship("Document", foreign_keys=[parent_document_id], remote_side=[id])
    uploaded_by_user = relationship("User", back_populates="uploaded_documents")
    lab_results = relationship("LabResult", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")

    outgoing_note_links = relationship(
        "NoteDocumentLink",
        foreign_keys="NoteDocumentLink.note_document_id",
        back_populates="note_document",
        cascade="all, delete-orphan",
    )
    incoming_note_links = relationship(
        "NoteDocumentLink",
        foreign_keys="NoteDocumentLink.linked_document_id",
        back_populates="linked_document",
        cascade="all, delete-orphan",
    )


class NoteDocumentLink(Base):
    __tablename__ = "note_document_links"

    id = Column(Integer, primary_key=True, index=True)
    note_document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    linked_document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)

    note_document = relationship(
        "Document",
        foreign_keys=[note_document_id],
        back_populates="outgoing_note_links",
    )
    linked_document = relationship(
        "Document",
        foreign_keys=[linked_document_id],
        back_populates="incoming_note_links",
    )
    created_by_user = relationship("User")

class UploadJob(Base):
    __tablename__ = "upload_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)

    section = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    saved_to = Column(String, nullable=False)

    status = Column(String, nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)

    # Set once classification runs (see process_upload_job / document_classifier).
    document_type = Column(String, nullable=True, index=True)
    classification_status = Column(String, nullable=True)
    classification_confidence = Column(Float, nullable=True)
    classification_source = Column(String, nullable=True)

    # Phase 2 — identity/duplicate safety. identity_override is set only by
    # POST /upload-jobs/{id}/confirm-identity (an audited manual override
    # after a needs_confirmation/mismatch review) and makes process_upload_job
    # skip the identity check entirely on the next run.
    file_sha256 = Column(String, nullable=True, index=True)
    identity_status = Column(String, nullable=True)
    identity_override = Column(Integer, nullable=False, default=0)

    created_at = Column(String, nullable=False)
    started_at = Column(String, nullable=True)
    finished_at = Column(String, nullable=True)

    user = relationship("User")
    patient = relationship("Patient")
    document = relationship("Document")

class LabResult(Base):
    __tablename__ = "lab_results"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)

    raw_test_name = Column(String, nullable=True)
    canonical_name = Column(String, nullable=True, index=True)
    display_name = Column(String, nullable=True)
    category = Column(String, nullable=True, index=True)
    source_section = Column(String, nullable=True)

    value = Column(String, nullable=True)
    flag = Column(String, nullable=True)
    reference_range = Column(String, nullable=True)
    unit = Column(String, nullable=True)

    # Phase 2 — canonical-observation groundwork. LabResult already carried
    # the raw/canonical split (raw_test_name vs. canonical_name/display_name/
    # category); these add the rest of the fields BRAGI_REDUCTO_PLAN.md calls
    # for, additively, rather than introducing a new ClinicalObservation
    # table that would require migrating every existing Analize query.
    observation_datetime = Column(String, nullable=True, index=True)
    institution = Column(String, nullable=True)
    specimen = Column(String, nullable=True)
    accession_id = Column(String, nullable=True)
    verification_state = Column(String, nullable=True, default="unverified")
    extraction_confidence = Column(Float, nullable=True)
    normalization_confidence = Column(Float, nullable=True)
    # How canonical_name/display_name were resolved from raw_test_name —
    # "exact" | "alias" | "ocr_fuzzy" | "unresolved" (see
    # app/services/lab_resolver.py). Provenance for the generic OCR-aware
    # analyte resolver: raw_test_name always stays the provider's literal
    # output regardless of this.
    normalization_method = Column(String, nullable=True)
    # Set when Level-3 duplicate-observation detection links this row to an
    # earlier one describing the same measurement instead of inserting a
    # second row for it (see process_upload_job).
    duplicate_of_lab_result_id = Column(Integer, ForeignKey("lab_results.id", ondelete="SET NULL"), nullable=True)

    # Interoperability — both null for every existing/uploaded row. Set only
    # by app/services/interop/fhir_connector.py's commit path; used for
    # idempotent re-sync (the same partner Observation.id syncing twice
    # updates this row instead of inserting a duplicate) and for tracing a
    # value back to the connection that produced it.
    source_connection_id = Column(Integer, ForeignKey("interop_connections.id", ondelete="SET NULL"), nullable=True, index=True)
    external_observation_id = Column(String, nullable=True, index=True)

    document = relationship("Document", back_populates="lab_results")
    source_evidence = relationship("SourceEvidence", back_populates="lab_result", cascade="all, delete-orphan")


class SourceEvidence(Base):
    """Provenance: where a clinical fact came from, down to the source text.

    Phase 2 populates `document_id` + `source_text` (+ `page_number` where
    known) for lab rows; normalized bbox coordinates are left null until a
    real Reducto Parse integration (Phase 3+) can supply them — no bbox is
    ever fabricated. `lab_result_id` is nullable because SourceEvidence is
    meant to generalize to other clinical entities (diagnoses, medications,
    procedures) in later phases, not just lab rows.
    """

    __tablename__ = "source_evidence"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    lab_result_id = Column(Integer, ForeignKey("lab_results.id"), nullable=True, index=True)

    page_number = Column(Integer, nullable=True)
    bbox_x = Column(Float, nullable=True)
    bbox_y = Column(Float, nullable=True)
    bbox_width = Column(Float, nullable=True)
    bbox_height = Column(Float, nullable=True)

    # Presentation-only geometry for laboratory evidence: the union of every
    # field-level citation bbox captured for this lab row (test name, value,
    # unit, reference range - whichever were returned), padded outward a
    # little so the UI can frame the whole row rather than a single cell.
    # Derived once at extraction time from real per-field bboxes above -
    # never a guessed/hardcoded region - and never overwrites them. Null
    # when there weren't at least two field bboxes to union (nothing
    # meaningfully wider than the raw bbox_* to compute), or for non-lab
    # evidence; callers fall back to bbox_* in that case.
    row_bbox_x = Column(Float, nullable=True)
    row_bbox_y = Column(Float, nullable=True)
    row_bbox_width = Column(Float, nullable=True)
    row_bbox_height = Column(Float, nullable=True)

    source_block_id = Column(String, nullable=True)
    source_text = Column(Text, nullable=True)

    extraction_confidence = Column(Float, nullable=True)
    provider = Column(String, nullable=True)
    parser_version = Column(String, nullable=True)

    created_at = Column(String, nullable=False)

    document = relationship("Document")
    lab_result = relationship("LabResult", back_populates="source_evidence")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    actor = Column(String, nullable=True)
    timestamp = Column(String, nullable=False)
    details = Column(Text, nullable=True)

    document = relationship("Document", back_populates="audit_logs")


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    # ondelete="SET NULL" documents the real constraint (added by the old
    # run_migrations() — see alembic/versions/0001_legacy_baseline.py's
    # matching comment) — this audit row survives a patient's account
    # deletion, detached rather than blocking or being deleted with it.
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True)
    doctor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    timestamp = Column(String, nullable=False)
    details = Column(Text, nullable=True)

    admin_user = relationship("User", foreign_keys=[admin_user_id])
    doctor_user = relationship("User", foreign_keys=[doctor_user_id])
    patient = relationship("Patient")


class DoctorDocumentReview(Base):
    __tablename__ = "doctor_document_reviews"

    id = Column(Integer, primary_key=True, index=True)
    doctor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    reviewed_at = Column(String, nullable=False)

    doctor_user = relationship("User", foreign_keys=[doctor_user_id])
    document = relationship("Document")


class PatientCarePartnerCode(Base):
    __tablename__ = "patient_care_partner_codes"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, unique=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(String, nullable=False)

    patient = relationship("Patient")


class CarePartnerPatientLink(Base):
    __tablename__ = "care_partner_patient_links"

    id = Column(Integer, primary_key=True, index=True)
    care_partner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    linked_at = Column(String, nullable=False)

    care_partner_user = relationship("User", foreign_keys=[care_partner_user_id])
    patient = relationship("Patient")


class SharedStructuredPage(Base):
    __tablename__ = "shared_structured_pages"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    care_partner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    shared_by_patient_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    shared_at = Column(String, nullable=False)

    document = relationship("Document")
    care_partner_user = relationship("User", foreign_keys=[care_partner_user_id])
    shared_by_patient_user = relationship("User", foreign_keys=[shared_by_patient_user_id])


class PatientMedication(Base):
    __tablename__ = "patient_medications"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    name = Column(String, nullable=False, index=True)
    dose_strength = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="active", index=True)
    route_form = Column(String, nullable=True)
    start_date = Column(String, nullable=True)
    stop_date = Column(String, nullable=True)
    prescriber = Column(String, nullable=True)
    extra_info = Column(Text, nullable=True)
    is_uncertain = Column(Integer, nullable=False, default=0)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=True)

    official_match_status = Column(String, nullable=True)
    official_source_name = Column(String, nullable=True)
    official_source_url = Column(String, nullable=True)
    rxnorm_rxcui = Column(String, nullable=True)
    dailymed_setid = Column(String, nullable=True)
    official_info_json = Column(Text, nullable=True)
    official_retrieved_at = Column(String, nullable=True)
    official_label_date = Column(String, nullable=True)

    patient = relationship("Patient", back_populates="medications")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    contact_relationship = Column("relationship", String, nullable=True)
    phone = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

    patient = relationship("Patient", back_populates="emergency_contacts")


class EmergencyAccessSession(Base):
    __tablename__ = "emergency_access_sessions"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, nullable=True, unique=True, index=True)
    emergency_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Nullable (not the original NOT NULL) so this access-audit record can
    # outlive the patient row it names: account deletion detaches the
    # reference (ON DELETE SET NULL — now declared here directly; see
    # alembic/versions/0001_legacy_baseline.py, previously only applied by
    # the old run_migrations()) rather than either deleting a real
    # access-audit record or being blocked by it — see
    # docs/privacy/RETENTION_POLICY.md.
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True)
    reason = Column(String, nullable=False)
    reason_note = Column(Text, nullable=True)
    started_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)
    closed_at = Column(String, nullable=True)
    revoked_at = Column(String, nullable=True)
    revoked_reason = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

    emergency_user = relationship("User", foreign_keys=[emergency_user_id])
    patient = relationship("Patient")


class AskBragiConversation(Base):
    """Ask Bragi conversation — a scoped, authorized chat over a single
    patient's Bragi record (or a single document within it). Bragi owns
    this row as the authoritative conversation record; OpenAI is never
    relied on to retain conversation state (see
    app/services/ask_bragi/service.py, `store=False`).

    `patient_id` is set once at creation time from a SERVER-validated
    authorization check (see app/services/ask_bragi/context.py) and never
    changes — it is never taken from a tool argument the model can
    influence. `scope`/`document_id` narrow a conversation to a single
    document ("document" scope) instead of the whole record
    ("patient_record" scope, the default) — see main.py's
    `POST /ask-bragi/conversations`.
    """

    __tablename__ = "ask_bragi_conversations"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, nullable=True, unique=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    scope = Column(String, nullable=False, default="patient_record")  # "patient_record" | "document"
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    owner_role = Column(String, nullable=False)  # role at creation time (patient | doctor)
    title = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=True)
    archived_at = Column(String, nullable=True)

    owner_user = relationship("User", foreign_keys=[owner_user_id])
    patient = relationship("Patient")
    document = relationship("Document")
    messages = relationship(
        "AskBragiMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AskBragiMessage.id",
    )


class AskBragiMessage(Base):
    """One turn in an Ask Bragi conversation. `citations_json`/`chart_json`
    are the server-VALIDATED final response (never the model's raw,
    unchecked output — see `service.py`'s citation-validation step).
    `tool_categories_json` is a short audit trail (which tool NAMES were
    invoked, not their inputs/outputs/PHI) — see main.py's audit-logging
    convention discussion in BRAGI_ASK_BRAGI_PLAN.md."""

    __tablename__ = "ask_bragi_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("ask_bragi_conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    citations_json = Column(Text, nullable=True)
    chart_json = Column(Text, nullable=True)
    follow_ups_json = Column(Text, nullable=True)
    status = Column(String, nullable=True)
    # "document" | "patient_record" — the scope this specific turn actually
    # used, which can differ from the conversation's own stored `scope`
    # (see AskBragiConversation) when a document-scoped turn was visibly
    # broadened — see app/services/ask_bragi/context.py's `turn_scope`.
    scope_used = Column(String, nullable=True)
    tool_categories_json = Column(Text, nullable=True)
    prompt_version = Column(String, nullable=True)
    tool_schema_version = Column(String, nullable=True)
    model = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

    conversation = relationship("AskBragiConversation", back_populates="messages")


class EmergencyAuditLog(Base):
    __tablename__ = "emergency_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    # All three ondelete="SET NULL" — same real, run_migrations()-applied
    # delete rule as AdminActionLog/EmergencyAccessSession above (this is
    # an audit trail; it survives whatever it references being removed).
    emergency_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("emergency_access_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(String, nullable=False)

    emergency_user = relationship("User", foreign_keys=[emergency_user_id])
    patient = relationship("Patient")


# ============================================================================
# Interoperability (BRAGI_INTEROP_PLAN.md -- Phase 1: FHIR R4 inbound connector)
#
# All rows below are additive and inert until a real ConnectionProfile is
# created and INTEROP_FHIR_ENABLED=true; nothing here changes any existing
# query, route, or upload path. See app/services/interop/ for the connector
# implementation and app/main.py's `/admin/interop/*` routes for the API.
# ============================================================================


class InteropSecret(Base):
    """A secret (bearer token, client secret, private key, etc.) belonging to
    a ConnectionProfile, encrypted at rest (see app/services/interop/crypto.py)
    and referenced from the profile only by opaque `ref` -- never by value.
    Never returned by any API response; never included in profile export.
    """

    __tablename__ = "interop_secrets"

    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String, nullable=False, unique=True, index=True)
    ciphertext = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rotated_at = Column(String, nullable=True)


class InteropConnection(Base):
    """A versioned, declarative description of how Bragi talks to one partner
    (ConnectionProfile in the plan doc's vocabulary -- named InteropConnection
    here since `Connection` alone collides conceptually with DB connections).
    Every *_json column is a serialized JSON object, following this file's
    existing convention (see AskBragiMessage.tool_categories_json etc.)
    rather than introducing a new column type.
    """

    __tablename__ = "interop_connections"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, nullable=True, unique=True, index=True)
    name = Column(String, nullable=False)
    connector_type = Column(String, nullable=False, default="fhir", index=True)  # "fhir" only in Phase 1

    # Lifecycle -- see BRAGI_INTEROP_PLAN.md P68. Never a bare enabled/disabled
    # boolean: draft -> discovered -> validated -> shadow -> active -> paused
    # / degraded -> disabled.
    status = Column(String, nullable=False, default="draft", index=True)

    base_url = Column(String, nullable=False)
    fhir_version = Column(String, nullable=True)

    # Sandbox connections (see P22 / the synthetic dev fixture) are the only
    # ones ever allowed to target a private/loopback address -- see
    # app/services/interop/ssrf.py. Never true for a real partner in
    # production; the admin route that sets it refuses outside
    # ENVIRONMENT != "production".
    allow_private_network = Column(Boolean, nullable=False, default=False)

    auth_type = Column(String, nullable=False, default="none")
    # Non-secret auth configuration only (issuer, audience, token_url, header
    # name, scopes...). Secret material is never stored here -- see
    # `secret_ref` below and app/services/interop/crypto.py.
    auth_config_json = Column(Text, nullable=True)
    secret_ref = Column(String, ForeignKey("interop_secrets.ref"), nullable=True)

    # {"primary_system": "...", "secondary_system": "..."} -- the identifier
    # system(s) this partner is trusted to assert identity through (P34).
    # Never guessed from whichever identifier a resource happens to list
    # first.
    patient_identity_json = Column(Text, nullable=True)

    # Cached CapabilityStatement-derived FhirCompatibilityReport (P11) plus
    # SMART discovery metadata (P6), with a timestamp -- see
    # app/services/interop/capability.py. Re-discoverable on demand; never
    # silently re-fetched on a normal request.
    capabilities_json = Column(Text, nullable=True)
    capabilities_discovered_at = Column(String, nullable=True)

    # Declarative mapping overrides (P15) -- schema-validated, non-executable;
    # see app/services/interop/mapping.py.
    terminology_overrides_json = Column(Text, nullable=True)

    # {"mode": "incremental"|"full", "poll_interval_seconds": ...} -- Phase 1
    # only records the config; the sync itself is admin-triggered, not a
    # background poller yet (see BRAGI_INTEROP_PLAN.md "Deferred").
    sync_config_json = Column(Text, nullable=True)

    version = Column(Integer, nullable=False, default=1)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    change_reason = Column(String, nullable=True)

    created_by_user = relationship("User", foreign_keys=[created_by_user_id])


class InteropSyncRun(Base):
    """One execution of discover / test / preview (shadow sync) / sync
    against a connection -- the audit trail behind the sync-diff UI (P67) and
    the data-quality dashboard (P72). `summary_json` holds the counts shown
    to the admin (patients discovered, observations, mapped_automatically,
    requires_mapping_review, unmapped_terminology, identity_conflicts,
    duplicates_detected, created/updated/skipped). `preview`/`test`/`discover`
    runs never write to any other table; only a `sync` run does.
    """

    __tablename__ = "interop_sync_runs"

    id = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, ForeignKey("interop_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    run_type = Column(String, nullable=False, index=True)  # discover | test | preview | sync
    status = Column(String, nullable=False, default="running", index=True)  # running | succeeded | failed
    summary_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(String, nullable=False)
    finished_at = Column(String, nullable=True)
    started_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    connection = relationship("InteropConnection")
    started_by_user = relationship("User", foreign_keys=[started_by_user_id])


class ExternalPatientIdentityLink(Base):
    """Explicit, admin-verified crosswalk between one external identifier
    (system + value) seen through one connection and one Bragi patient
    (P31/P32). No row here is ever created automatically from a fuzzy/name
    match -- only from an explicit admin action, or a verified PIXm/PDQm
    result in a later phase. A conflicting identifier (already linked to a
    different patient) is recorded in InteropIdentityConflict instead of
    overwriting this table.
    """

    __tablename__ = "interop_patient_identity_links"

    id = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, ForeignKey("interop_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    identifier_system = Column(String, nullable=False, index=True)
    identifier_value = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="verified", index=True)  # verified | pending | revoked
    verification_method = Column(String, nullable=True)  # "admin_manual" in Phase 1
    verified_at = Column(String, nullable=True)
    verified_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, nullable=False)

    connection = relationship("InteropConnection")
    patient = relationship("Patient")
    verified_by_user = relationship("User", foreign_keys=[verified_by_user_id])


class InteropIdentityConflict(Base):
    """Recorded whenever a sync sees an external identifier already linked
    (via ExternalPatientIdentityLink) to a DIFFERENT Bragi patient than the
    one the current sync context expected. The sync stops for that identity
    and imports nothing for it (P33) until an admin resolves this row.
    """

    __tablename__ = "interop_identity_conflicts"

    id = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, ForeignKey("interop_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    identifier_system = Column(String, nullable=False)
    identifier_value = Column(String, nullable=False)
    existing_link_id = Column(Integer, ForeignKey("interop_patient_identity_links.id"), nullable=True)
    attempted_patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    detected_at = Column(String, nullable=False)
    resolved = Column(Boolean, nullable=False, default=False, index=True)
    resolved_at = Column(String, nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolution_note = Column(Text, nullable=True)

    connection = relationship("InteropConnection")
    existing_link = relationship("ExternalPatientIdentityLink")
    attempted_patient = relationship("Patient")


class InteropTerminologyMapping(Base):
    """A local (partner-specific) code seen through one connection, mapped to
    a Bragi canonical lab concept -- either an admin-approved override (P15)
    or surfaced for review after `resolve_analyte()` couldn't confidently
    resolve it (P73). Approval is never automatic from frequency alone.
    """

    __tablename__ = "interop_terminology_mappings"

    id = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, ForeignKey("interop_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    source_system = Column(String, nullable=True)
    source_code = Column(String, nullable=True, index=True)
    source_display = Column(String, nullable=True)
    target_canonical_name = Column(String, nullable=True)
    target_display_name = Column(String, nullable=True)
    target_category = Column(String, nullable=True)
    target_unit = Column(String, nullable=True)
    mapping_type = Column(String, nullable=False, default="pending_review")  # local_override | pending_review
    status = Column(String, nullable=False, default="pending", index=True)  # pending | approved
    frequency_seen = Column(Integer, nullable=False, default=1)
    example_json = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)
    approved_at = Column(String, nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    connection = relationship("InteropConnection")
    approved_by_user = relationship("User", foreign_keys=[approved_by_user_id])