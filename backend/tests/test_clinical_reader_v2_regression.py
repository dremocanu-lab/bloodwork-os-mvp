"""Clinical Reader Intelligence V2 — regression tests against the full
synthetic Romanian discharge fixture (Part 28). Covers the lettered
Part 29 items not already exercised by test_clinical_document_
ai_interpreter.py / test_clinical_document_template_detection.py /
test_clinical_document_reprocessing.py's smaller inline fixtures:
current-vs-historical demographics authority, blank-secondary-diagnosis
suppression, empty-template suppression for a real Romanian document
shape, repeated-procedure preservation vs verbatim-duplicate flagging,
suspicious-date/vital-sign preservation, typed-investigation recognition
(JAK2/bone marrow biopsy/abdominal ultrasound/BCR-ABL), treatment-era
grounding, current-encounter exclusion of historical events, and (one
DB-backed test) a genuine lab conflict surviving the real text-
extraction path end to end.

Section A runs the real deterministic parser only (no DB, no AI) —
`parse_legacy_discharge_payload` is pure and fast. Section B adds a
hand-built, REALISTIC mocked AI interpreter response (grounded in the
document's own REAL ids, discovered by inspection rather than hardcoded
strings, so this stays robust to segment-id formatting details) and
runs it through the real `validate_and_filter_interpretation`/
`apply_interpretation` — never a live OpenAI call, consistent with
Part 30's mocking requirement. Section C needs real DB connectivity and
is skipped when DATABASE_URL isn't configured, same convention as the
other clinical_document persistence test files.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

from app.services.clinical_document import ai_interpreter  # noqa: E402
from app.services.clinical_document.ai_interpreter import (  # noqa: E402
    apply_interpretation,
    validate_and_filter_interpretation,
)
from app.services.clinical_document.discharge_parser import parse_legacy_discharge_payload  # noqa: E402
from app.services.clinical_document.schema import ClinicalEvent, StructuredClinicalDocument  # noqa: E402
from tests.fixtures.clinical_reader_v2_fixture import SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD  # noqa: E402


def _document() -> StructuredClinicalDocument:
    return parse_legacy_discharge_payload(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD)


def _section(document: StructuredClinicalDocument, canonical_key: str):
    return next(s for s in document.sections if s.canonical_key == canonical_key)


def _event_containing(document: StructuredClinicalDocument, text: str) -> ClinicalEvent:
    return next(e for e in document.dated_events if text in e.raw_text)


def _events_containing(document: StructuredClinicalDocument, text: str) -> list[ClinicalEvent]:
    return [e for e in document.dated_events if text in e.raw_text]


# ─── Section A: the real deterministic parser, no AI, no DB ───────────────


def test_historical_narrative_age_never_overwrites_current_administrative_demographics():
    """Part 15 — the historical narrative mentions '52 de ani' (the
    patient's age back in 2018); metadata must stay exactly what the
    administrative payload fields said, never derived from narrative
    text at all."""
    document = _document()
    assert document.metadata.date_of_birth == "1968-01-15"
    assert document.metadata.patient_name == "Popescu Maria (synthetic test patient)"
    # The historical age reference is real narrative content, not deleted
    # — it just never becomes administrative fact. It has no DD.MM.YYYY
    # date of its own (just "anul 2018"), so it lives in the section's
    # text rather than as a dated event — metadata is still untouched by
    # it either way, which is the actual invariant under test.
    clinical_course_text = "\n".join(b.text for b in _section(document, "clinical_course").blocks)
    assert "52 de ani" in clinical_course_text
    assert document.metadata.date_of_birth != "2018"


def test_principal_diagnosis_extracted_blank_secondary_field_never_becomes_content():
    """Part 1C / 29 — D45 is real, filled clinical content; the blank
    secondary field sits right next to it in the SAME canonical section
    but must never render as if it were a real diagnosis value."""
    document = _document()
    diagnoses_section = _section(document, "diagnoses")
    assert diagnoses_section.is_template_only is False  # real content (D45) keeps the section visible
    block_texts = [b.text for b in diagnoses_section.blocks]
    assert any("D45" in t for t in block_texts)
    assert any(t.strip() == "____" for t in block_texts)  # the blank field survives verbatim, unrendered as content


def test_empty_treatment_template_is_suppressed_from_the_intelligent_reader():
    """Part 1E / 12 — a 'PRODUS / CANTITATE' table with nothing filled in
    must never be presented as if it were real treatment content."""
    document = _document()
    treatment_section = _section(document, "treatment")
    assert treatment_section.is_template_only is True


def test_empty_investigations_template_is_suppressed_while_narrative_investigations_survive():
    """Part 1D / 12 — the explicit 'Investigatii' form box is blank
    boilerplate; the REAL investigations (JAK2, biopsy, ultrasound,
    BCR-ABL) live in the Clinical Course narrative instead and are
    untouched by this suppression."""
    document = _document()
    investigations_section = _section(document, "investigations")
    assert investigations_section.is_template_only is True
    clinical_course_text = "\n".join(b.text for b in _section(document, "clinical_course").blocks)
    for marker in ("JAK2", "osteomedulara", "ecografie abdominala", "BCR-ABL"):
        assert marker in clinical_course_text


def test_repeated_phlebotomy_events_at_different_dates_are_all_preserved_as_distinct():
    """Part 9 — the same PROCEDURE recurring over time (therapeutic
    phlebotomy) across three real, different dates must remain three
    distinct events, none of them collapsed or flagged as a duplicate
    (their text differs — each names its own date)."""
    document = _document()
    phlebotomy_events = _events_containing(document, "flebotomie terapeutica")
    assert len(phlebotomy_events) == 3
    assert {e.normalized_date for e in phlebotomy_events} == {"2019-05-10", "2020-11-22", "2021-03-14"}
    assert all(not e.is_repeated_in_source for e in phlebotomy_events)


def test_verbatim_duplicated_narrative_block_is_flagged_repeated_never_deleted():
    """Part 1J / 16 — an exact verbatim repeat of the SAME dated
    narrative sentence (a realistic two-page-extraction artifact) must
    survive as two events (nothing deleted, both keep their own source
    reference) with only the SECOND occurrence flagged as a repeat."""
    document = _document()
    repeated = _events_containing(document, "control hematologic: se mentine tratamentul")
    assert len(repeated) == 2
    assert repeated[0].is_repeated_in_source is False
    assert repeated[1].is_repeated_in_source is True
    # Both still carry their own real source_evidence/segment identity —
    # nothing about the second occurrence was deleted or merged away.
    assert repeated[0].source_event_id != repeated[1].source_event_id


def test_suspicious_far_future_date_is_preserved_verbatim_and_flagged_not_corrected():
    """Part 1I / 14 — a year-3036 typo must never be silently 'fixed' to
    a plausible year; it stays exactly as written, with a warning."""
    document = _document()
    event = _event_containing(document, "14.09.3036")
    assert event.raw_date_text == "14.09.3036"
    assert event.normalized_date == "3036-09-14"  # preserved as-is, not corrected to e.g. 2026
    assert any("outside the plausible range" in w for w in event.warnings)


def test_implausible_vital_sign_is_preserved_verbatim_and_flagged_not_corrected():
    """Part 1I / 14 — 'AV 1008/min' is physiologically impossible but
    must never be silently rewritten; the raw text stays exactly as
    extracted and a document-level warning is raised instead."""
    document = _document()
    admission_event = _event_containing(document, "AV 1008")
    assert "AV 1008/min" in admission_event.raw_text  # never altered
    assert any("AV" in w and "1008" in w for w in document.warnings)


def test_prescription_issued_mention_stays_distinct_narrative_not_an_administered_medication():
    """Part 9B — 'a fost eliberata reteta' (a prescription was issued) is
    kept as its own narrative event; nothing in the deterministic parser
    promotes this to a confirmed-administered medication record."""
    document = _document()
    prescription_event = _event_containing(document, "a fost eliberata reteta")
    assert "Besremi" in prescription_event.raw_text
    assert prescription_event.event_type != "treatment_change"  # never guessed as an administered change


# ─── Section B: AI interpreter grounding contract, mocked, against the
# full fixture — never a live model call (Part 30). ────────────────────


def _event_id_containing(document: StructuredClinicalDocument, text: str) -> str:
    return _event_containing(document, text).source_event_id


def test_ai_interpreter_recognizes_investigation_types_buried_in_narrative():
    """Part 10 / 29 — JAK2 V617F (molecular), bone marrow biopsy
    (pathology), abdominal ultrasound (imaging) and BCR-ABL (molecular)
    are all embedded in prose, not in an explicit investigations field —
    a realistic grounded model response should place them with the right
    types, and the grounding gate should accept every one of them since
    they cite the document's own real ids."""
    document = _document()
    clinical_course_id = _section(document, "clinical_course").id
    # The historical onset narrative ("anul 2018 ... JAK2 V617F ...
    # biopsie osteomedulara") has no DD.MM.YYYY date of its own, so it
    # produced no ClinicalEvent — grounding for these two goes through
    # source_section_id only, exactly as a real model response would.
    current_event_id = _event_id_containing(document, "ecografie abdominala")

    raw = {
        "diagnoses": [],
        "investigations": [
            {
                "investigation_type": "molecular",
                "title": "JAK2 V617F",
                "findings": "Mutatia JAK2 V617F pozitiva.",
                "conclusion": None,
                "source_section_id": clinical_course_id,
                "source_event_ids": [],
            },
            {
                "investigation_type": "pathology",
                "title": "Biopsie osteomedulara",
                "findings": None,
                "conclusion": None,
                "source_section_id": clinical_course_id,
                "source_event_ids": [],
            },
            {
                "investigation_type": "imaging",
                "title": "Ecografie abdominala",
                "findings": "Splenomegalie moderata, fara alte modificari semnificative.",
                "conclusion": None,
                "source_section_id": clinical_course_id,
                "source_event_ids": [current_event_id],
            },
            {
                "investigation_type": "molecular",
                "title": "BCR-ABL",
                "findings": "Rezultat negativ.",
                "conclusion": "Exclude leucemia mieloida cronica.",
                "source_section_id": clinical_course_id,
                "source_event_ids": [current_event_id],
            },
        ],
        "anomalies": [],
        "recommendations": [],
        "treatment_eras": [],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert rejections == []
    result = apply_interpretation(document, cleaned, status="complete", warnings=[])
    types_by_title = {inv.title: inv.investigation_type for inv in result.investigations}
    assert types_by_title["JAK2 V617F"] == "molecular"
    assert types_by_title["Biopsie osteomedulara"] == "pathology"
    assert types_by_title["Ecografie abdominala"] == "imaging"
    assert types_by_title["BCR-ABL"] == "molecular"


def test_ai_interpreter_never_fabricates_a_diagnosis_for_the_blank_secondary_field():
    """Part 7 / 29 — a realistic grounded response extracts ONLY the real
    principal diagnosis; there is nothing to cite for the blank
    secondary field, so a well-behaved model response simply omits it —
    the reader must show exactly that one diagnosis, not an invented
    'no secondary diagnoses' item and not a fabricated second one."""
    document = _document()
    diagnoses_section_id = _section(document, "diagnoses").id
    raw = {
        "diagnoses": [
            {
                "code": "D45",
                "text": "Policitemie vera",
                "role": "principal",
                "source_section_id": diagnoses_section_id,
                "source_event_ids": [],
            }
        ],
        "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert rejections == []
    result = apply_interpretation(document, cleaned, status="complete", warnings=[])
    assert len(result.diagnoses) == 1
    assert result.diagnoses[0].role == "principal"
    assert result.diagnoses[0].code == "D45"


def test_ai_interpreter_grounds_treatment_eras_in_the_documents_real_events():
    """Part 9 / 29 — Hydrea -> ruxolitinib -> Besremi (with a dose
    change) is a real, evidence-backed progression; a treatment era must
    cite real event ids from THIS document, and does here."""
    document = _document()
    ruxolitinib_event_id = _event_id_containing(document, "trecerea de la Hidroxiuree la Ruxolitinib")
    besremi_start_id = _event_id_containing(document, "s-a initiat tratament cu Besremi")
    besremi_dose_id = _event_id_containing(document, "doza de Besremi a fost crescuta")

    raw = {
        "diagnoses": [], "investigations": [], "anomalies": [], "recommendations": [],
        "treatment_eras": [
            {
                "label": "Ruxolitinib",
                "start_date": "2022-09-18",
                "end_date": "2024-02-05",
                "description": "Trecere de la Hidroxiuree la Ruxolitinib pentru intoleranta digestiva.",
                "event_ids": [ruxolitinib_event_id],
            },
            {
                "label": "Besremi (ropeginterferon alfa-2b)",
                "start_date": "2024-02-05",
                "end_date": None,
                "description": "Initiere Besremi 100mcg, ulterior titrare la 150mcg.",
                "event_ids": [besremi_start_id, besremi_dose_id],
            },
        ],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert rejections == []
    result = apply_interpretation(document, cleaned, status="complete", warnings=[])
    assert len(result.treatment_eras) == 2
    besremi_era = next(era for era in result.treatment_eras if era.label.startswith("Besremi"))
    assert set(besremi_era.event_ids) == {besremi_start_id, besremi_dose_id}


def test_ai_interpreter_anomaly_flags_preserve_original_values_verbatim():
    """Part 14 / 29 — a grounded anomaly report for the year-3036 date
    and the AV-1008 vital sign must carry the EXACT source text in
    `original_value`, never a 'corrected' reading."""
    document = _document()
    clinical_course_id = _section(document, "clinical_course").id
    anomalous_date_event_id = _event_id_containing(document, "14.09.3036")
    raw = {
        "diagnoses": [], "investigations": [], "recommendations": [], "treatment_eras": [],
        "anomalies": [
            {
                "anomaly_type": "impossible_or_unusual_date",
                "message": "Prescription date falls far outside any plausible range.",
                "original_value": "14.09.3036",
                "source_section_id": None,
                "source_event_ids": [anomalous_date_event_id],
            },
            {
                "anomaly_type": "physiologically_implausible_value",
                "message": "Heart rate of 1008/min is not physiologically possible.",
                "original_value": "AV 1008/min",
                "source_section_id": clinical_course_id,
                "source_event_ids": [],
            },
        ],
        "current_encounter": {"admission_date": None, "discharge_date": None, "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert rejections == []
    result = apply_interpretation(document, cleaned, status="complete", warnings=[])
    original_values = {a.original_value for a in result.anomalies}
    assert original_values == {"14.09.3036", "AV 1008/min"}


def test_ai_interpreter_current_encounter_excludes_historical_events():
    """Part 15 / 7C — the current hospitalization (04-05.03.2026) must
    only ever be assembled from events the model placed in
    current_encounter, never from historical narrative — a 2019
    phlebotomy event must never end up there even if cited elsewhere."""
    document = _document()
    admission_event_id = _event_id_containing(document, "AV 1008")
    discharge_event_id = _event_id_containing(document, "in stare ameliorata")
    historical_phlebotomy_id = _event_id_containing(document, "10.05.2019")

    raw = {
        "diagnoses": [], "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
        "current_encounter": {
            "admission_date": "2026-03-04",
            "discharge_date": "2026-03-05",
            "section_ids": [],
            "event_ids": [admission_event_id, discharge_event_id],
        },
        "encounter_scope_assignments": [
            {"target_type": "event", "target_id": admission_event_id, "scope": "current"},
            {"target_type": "event", "target_id": discharge_event_id, "scope": "current"},
            {"target_type": "event", "target_id": historical_phlebotomy_id, "scope": "historical"},
        ],
        "warnings": [],
    }
    cleaned, rejections = validate_and_filter_interpretation(raw, document)
    assert rejections == []
    result = apply_interpretation(document, cleaned, status="complete", warnings=[])
    assert set(result.current_encounter.event_ids) == {admission_event_id, discharge_event_id}
    assert historical_phlebotomy_id not in result.current_encounter.event_ids
    historical_event = next(e for e in result.dated_events if e.source_event_id == historical_phlebotomy_id)
    assert historical_event.encounter_scope == "historical"
    admission_event = next(e for e in result.dated_events if e.source_event_id == admission_event_id)
    assert admission_event.encounter_scope == "current"


# ─── Section C: real DB, real extraction pipeline (labs conflict) ─────────

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL not configured — Section C needs real DB connectivity.", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.clinical_document.reprocessing import reprocess_discharge_document  # noqa: E402

client = TestClient(app)


def _unique_email(label: str) -> str:
    return f"clindoc-v2fixture-{label}-{uuid.uuid4().hex[:10]}@example.com"


def _signup(role: str, **extra) -> dict:
    email = _unique_email(role)
    payload = {"email": email, "full_name": f"V2 Fixture Test {role}", "password": "TestPass123!", "role": role, **extra}
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["access_token"], "user": data["user"], "email": email}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def synthetic_fixture_document():
    account = _signup("patient", cnp="6000101999985")
    profile = client.get("/my/profile", headers=_auth(account["token"])).json()
    patient_id = profile["patient"]["id"]

    db = SessionLocal()
    try:
        doc = models.Document(
            patient_id=patient_id,
            section="discharge_summary",
            filename="synthetic-discharge-fixture.pdf",
            document_type="discharge_summary",
            report_name="Synthetic Discharge Fixture",
            created_at="2026-03-05T00:00:00Z",
            is_verified=False,
            public_id=f"brg-doc-v2fixture-{uuid.uuid4().hex[:8]}",
            note_body=json.dumps(SYNTHETIC_ROMANIAN_DISCHARGE_PAYLOAD),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        document_id = doc.id
    finally:
        db.close()

    yield {"account": account, "patient_id": patient_id, "document_id": document_id}

    client.delete("/my/account", headers=_auth(account["token"]))


def _fake_call_model_no_interpretation(_input):
    return {
        "diagnoses": [], "investigations": [], "anomalies": [], "recommendations": [], "treatment_eras": [],
        "current_encounter": {"admission_date": "2026-03-04", "discharge_date": "2026-03-05", "section_ids": [], "event_ids": []},
        "encounter_scope_assignments": [],
        "warnings": [],
    }


def test_reprocessing_synthetic_fixture_preserves_conflicting_hgb_lab_values(synthetic_fixture_document, monkeypatch):
    """Part 1H / 8F end to end: two different HGB values from the SAME
    real discharge text, run through the REAL extraction/persistence
    pipeline (not a hand-built LabCandidate), must both survive as
    separate rows, neither silently picked as 'the' correct one."""
    monkeypatch.setattr(ai_interpreter, "_call_model", _fake_call_model_no_interpretation)
    db = SessionLocal()
    try:
        document = db.query(models.Document).filter(models.Document.id == synthetic_fixture_document["document_id"]).first()
        result = reprocess_discharge_document(db, document=document, actor_user_id=synthetic_fixture_document["account"]["user"]["id"])
        assert result.lab_results_created >= 5  # WBC, HGB x2, PLT, Glucoza, INR

        hgb_rows = (
            db.query(models.LabResult)
            .filter(models.LabResult.document_id == document.id, models.LabResult.raw_test_name == "HGB")
            .all()
        )
        assert len(hgb_rows) == 2
        values = {row.value for row in hgb_rows}
        assert values == {"9.8", "11.2"}
        assert all(row.verification_state == "conflict" for row in hgb_rows)
    finally:
        db.close()
