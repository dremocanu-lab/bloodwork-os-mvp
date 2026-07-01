from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


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
    documents = relationship("Document", back_populates="patient")
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

    is_verified = Column(Integer, nullable=False, default=0)
    verified_by = Column(String, nullable=True)
    verified_at = Column(String, nullable=True)
    last_edited_at = Column(String, nullable=True)
    created_at = Column(String, nullable=True)

    patient = relationship("Patient", back_populates="documents")
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

    document = relationship("Document", back_populates="lab_results")


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
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
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
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
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


class EmergencyAuditLog(Base):
    __tablename__ = "emergency_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    emergency_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("emergency_access_sessions.id"), nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(String, nullable=False)

    emergency_user = relationship("User", foreign_keys=[emergency_user_id])
    patient = relationship("Patient")