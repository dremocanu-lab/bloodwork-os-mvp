"""Synthetic, non-PHI sample document text used by classifier/pipeline tests.

None of this is real patient data — names, values, and IDs are invented
for testing shape/vocabulary recognition only. Per BRAGI_REDUCTO_PLAN.md,
never substitute real production documents here.
"""

ROMANIAN_LAB_REPORT = """
BULETIN DE ANALIZE MEDICALE
Laborator Synevo Cluj

Pacient: Popescu Ion Test
CNP: 1900101123456
Data recoltarii: 12.08.2026

HEMATOLOGIE
Hemoglobina           14.8 g/dL      13.5-17.5
Leucocite             12.1 10^3/uL   4.0-10.0   H
Trombocite            243  10^3/uL   150-400
Eritrocite            4.82 10^6/uL   4.5-5.9

BIOCHIMIE
Creatinina            1.18 mg/dL     0.7-1.3
Glicemie               92 mg/dL      70-100
CRP                    37 mg/L       <5         H

Valorile de referinta pot varia in functie de metoda de laborator.
"""

ENGLISH_LAB_REPORT = """
LABORATORY RESULTS
Regional Medical Laboratory

Patient: Jane Test Sample
Specimen: Venous blood
Collected: 2026-06-02

Complete Blood Count (CBC)
WBC        7.2   10^3/uL   Reference range 4.0-11.0
RBC        4.6   10^6/uL   Reference range 4.2-5.4
Hemoglobin 13.9  g/dL      Reference range 12.0-15.5

Basic Metabolic Panel
Glucose    95    mg/dL     Normal range 70-100
Creatinine 0.9   mg/dL     Normal range 0.6-1.2
"""

ROMANIAN_DISCHARGE_SUMMARY = """
SPITALUL CLINIC TEST FLOREASCA
FISA DE EXTERNARE / EPICRIZA

Pacient: Ionescu Maria Test
Data internarii: 05.08.2026
Data externarii: 08.08.2026
Sectie: Chirurgie Generala

Motivul internarii: Durere abdominala in etajul superior drept.

Diagnostic la externare: Colecistita acuta litiazica.

Evolutie: Pacienta a fost supusa unei colecistectomii laparoscopice
in ziua 2 de internare. Evolutie postoperatorie fara complicatii.

Tratament la externare: Continua Amoxicilina/Acid clavulanic 1g,
2 comprimate/zi, timp de 5 zile.

Recomandari la externare: Control chirurgical peste 7-10 zile.
Evitarea eforturilor fizice mari timp de 4 saptamani.
"""

ENGLISH_CT_REPORT = """
IMAGING REPORT
Modality: CT Abdomen and Pelvis with contrast
Exam date: 2026-08-03
Indication: Right upper quadrant pain, rule out cholecystitis.

Technique: Contiguous axial CT images were obtained through the abdomen
and pelvis following administration of intravenous contrast.

Comparison: None available.

Findings: The gallbladder is distended with wall thickening and
pericholecystic fat stranding. Liver, spleen, pancreas, and kidneys are
unremarkable. No free fluid.

Impression: Findings consistent with acute cholecystitis.
"""

PRESCRIPTION_TEXT = """
RETETA MEDICALA
Cod parafa: TEST12345
Pacient: Radu Test Pacient

Amoxicilina/Acid clavulanic 1g
Sig: 1 comprimat de 2 ori pe zi, timp de 7 zile.

Ibuprofen 400mg
Sig: 1 comprimat la nevoie pentru durere, maxim 3 pe zi.
"""

PATHOLOGY_TEXT = """
EXAMEN ANATOMOPATOLOGIC
Specimen: Colecist, piesa de colecistectomie.

Descriere macroscopica: Colecist de 7x3 cm, perete ingrosat.

Descriere microscopica: Mucoasa cu infiltrat inflamator cronic,
fara elemente de malignitate identificate in sectiunile examinate.

Diagnostic final: Colecistita cronica litiazica.
"""

CONSULTATION_TEXT = """
CONSULTATIE CARDIOLOGIE
Cabinet de specialitate cardiologie

Pacient: Test Pacient Trei
Motivul consultatiei: Palpitatii intermitente de 2 saptamani.

Anamneza: Fara antecedente cardiace cunoscute.
Examen clinic: TA 128/82 mmHg, AV 78/min, cord in ritm sinusal.

Diagnostic: Palpitatii de cauza incerta, probabil functionale.
Plan: EKG efectuat in cabinet, normal. Recomandare Holter EKG 24h.
"""

MEANINGLESS_FILENAME_LAB_TEXT = ROMANIAN_LAB_REPORT  # content should still classify correctly
MISLEADING_FILENAME_DISCHARGE_TEXT = ROMANIAN_DISCHARGE_SUMMARY  # filename may say "labs.pdf"

GARBLED_OCR_TEXT = "a b c . . . -- -- ___ 12 3 x x"

EMPTY_TEXT = ""
