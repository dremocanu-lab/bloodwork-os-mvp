"""Shared response-serialization helpers (BRAGI backend modularization,
Phase 4).

Moved verbatim from app/main.py, one function at a time as each caller
needs it outside main.py — see docs/refactor/BACKEND_DECOMPOSITION_PLAN.md
("Shared serialization helpers" candidates for schemas/ support code).
`serialize_patient_event` is used by the patients, PCP, and patient-events
domains; relocating it here (unchanged output shape) lets each import it
without a circular dependency on app.main.
"""

from __future__ import annotations


def serialize_patient_event(event) -> dict:
    doctor = event.doctor_user

    return {
        "id": event.id,
        "patient_id": event.patient_id,
        "doctor_user_id": event.doctor_user_id,
        "event_type": event.event_type,
        "status": event.status,
        "title": event.title,
        "description": event.description,
        "hospital_name": event.hospital_name,
        "department": event.department,
        "admitted_at": event.admitted_at,
        "discharged_at": event.discharged_at,
        "doctor_name": doctor.full_name if doctor else None,
    }
