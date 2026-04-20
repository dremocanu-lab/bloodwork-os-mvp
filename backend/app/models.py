from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, index=True)

    department = Column(String, nullable=True, index=True)
    hospital_name = Column(String, nullable=True, index=True)

    patient_profile = relationship("Patient", back_populates="linked_user", uselist=False)

    doctor_patient_links = relationship(
        "DoctorPatientAccess",
        foreign_keys="DoctorPatientAccess.doctor_user_id",
        back_populates="doctor_user",
        cascade="all, delete-orphan",
    )

    granted_access_links = relationship(
        "DoctorPatientAccess",
        foreign_keys="DoctorPatientAccess.granted_by_user_id",
        back_populates="granted_by_user",
    )

    requested_access_links = relationship(
        "DoctorPatientAccessRequest",
        foreign_keys="DoctorPatientAccessRequest.doctor_user_id",
        back_populates="doctor_user",
        cascade="all, delete-orphan",
    )

    uploaded_documents = relationship(
        "Document",
        foreign_keys="Document.uploaded_by_user_id",
        back_populates="uploaded_by_user",
    )

    created_events = relationship(
        "PatientEvent",
        foreign_keys="PatientEvent.created_by_user_id",
        back_populates="created_by_user",
    )

    discharged_events = relationship(
        "PatientEvent",
        foreign_keys="PatientEvent.discharged_by_user_id",
        back_populates="discharged_by_user",
    )


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    linked_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True)

    full_name = Column(String, nullable=False, index=True)
    date_of_birth = Column(String, nullable=True)
    age = Column(String, nullable=True)
    sex = Column(String, nullable=True)
    cnp = Column(String, nullable=True, index=True)
    patient_identifier = Column(String, nullable=True, index=True)

    linked_user = relationship("User", back_populates="patient_profile")
    documents = relationship("Document", back_populates="patient", cascade="all, delete-orphan")

    doctor_access_links = relationship(
        "DoctorPatientAccess",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    access_requests = relationship(
        "DoctorPatientAccessRequest",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    events = relationship(
        "PatientEvent",
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class DoctorPatientAccess(Base):
    __tablename__ = "doctor_patient_access"

    id = Column(Integer, primary_key=True, index=True)
    doctor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    granted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at = Column(String, nullable=False)

    doctor_user = relationship(
        "User",
        foreign_keys=[doctor_user_id],
        back_populates="doctor_patient_links",
    )
    granted_by_user = relationship(
        "User",
        foreign_keys=[granted_by_user_id],
        back_populates="granted_access_links",
    )
    patient = relationship("Patient", back_populates="doctor_access_links")


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

    doctor_user = relationship(
        "User",
        foreign_keys=[doctor_user_id],
        back_populates="requested_access_links",
    )
    patient = relationship("Patient", back_populates="access_requests")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    section = Column(String, nullable=False, default="bloodwork", index=True)

    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    saved_to = Column(String, nullable=False)
    extracted_text = Column(Text, nullable=True)

    patient_name = Column(String, nullable=True)
    date_of_birth = Column(String, nullable=True)
    age = Column(String, nullable=True)
    sex = Column(String, nullable=True)
    cnp = Column(String, nullable=True)
    patient_identifier = Column(String, nullable=True)

    report_name = Column(String, nullable=True)
    report_type = Column(String, nullable=True)
    lab_name = Column(String, nullable=True)
    sample_type = Column(String, nullable=True)
    referring_doctor = Column(String, nullable=True)
    source_language = Column(String, nullable=True)

    test_date = Column(String, nullable=True)
    collected_on = Column(String, nullable=True)
    reported_on = Column(String, nullable=True)
    registered_on = Column(String, nullable=True)
    generated_on = Column(String, nullable=True)

    is_verified = Column(Boolean, default=False, nullable=False)
    verified_by = Column(String, nullable=True)
    verified_at = Column(String, nullable=True)
    last_edited_at = Column(String, nullable=True)

    patient = relationship("Patient", back_populates="documents")
    uploaded_by_user = relationship("User", back_populates="uploaded_documents")
    labs = relationship("LabResult", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")


class LabResult(Base):
    __tablename__ = "lab_results"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)

    raw_test_name = Column(String, nullable=True)
    canonical_name = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    category = Column(String, nullable=True)

    value = Column(String, nullable=True)
    flag = Column(String, nullable=True)
    reference_range = Column(String, nullable=True)
    unit = Column(String, nullable=True)

    document = relationship("Document", back_populates="labs")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)

    action = Column(String, nullable=False)
    actor = Column(String, nullable=True)
    timestamp = Column(String, nullable=False)
    details = Column(Text, nullable=True)

    document = relationship("Document", back_populates="audit_logs")


class PatientEvent(Base):
    __tablename__ = "patient_events"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    doctor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    event_type = Column(String, nullable=False, default="hospitalization", index=True)
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
    created_by_user = relationship(
        "User",
        foreign_keys=[created_by_user_id],
        back_populates="created_events",
    )
    discharged_by_user = relationship(
        "User",
        foreign_keys=[discharged_by_user_id],
        back_populates="discharged_events",
    )