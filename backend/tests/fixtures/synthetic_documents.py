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

ROMANIAN_DISCHARGE_BILET_DE_IESIRE = """
BILET DE IEȘIRE DIN SPITAL / SCRISOARE MEDICALĂ
Spitalul Clinic Județean de Urgență
Secția: Hematologie

Pacient: Ionescu Maria Test
Data internarii: 04.03.2026
Data externarii: 05.03.2026

Diagnostic la internare: Anemie feripriva, sindrom mielodisplazic suspect.
Diagnostic la externare: D45 Policitemia vera.

EPICRIZA:
Pacienta s-a internat in sectia de Hematologie pentru evaluarea unui sindrom
anemic cronic insotit de astenie marcata. Pe parcursul internarii s-au
efectuat investigatii hematologice complete, biochimie si frotiu de sange
periferic. S-a stabilit diagnosticul de Policitemia vera (D45) in urma
evaluarii hemogramei complete si a markerilor moleculari.

Tratament administrat: flebotomie terapeutica, hidroxiuree 500mg 1-0-1.

Diagnostic principal: D45 Policitemia vera.

Recomandari la externare: Control hematologic peste 4 saptamani, continuarea
tratamentului cu hidroxiuree, evitarea deshidratarii, dieta bogata in fier.

EXAMENE DE LABORATOR:

Nr. cerere: LAB-2026-0341
Data recoltarii: 04.03.2026

Hemoleucograma completa:
WBC 8.20 10^3/uL, interval de referinta (4.0-10.0)
RBC 6.10 10^6/uL, interval de referinta (4.2-5.9), valoare crescuta
HGB 18.4 g/dL, interval de referinta (13.0-17.0), valoare crescuta
HCT 55.2 %, interval de referinta (40-52), valoare crescuta
PLT 512 10^3/uL, interval de referinta (150-400), valoare crescuta
MCV 88.0 fL, interval de referinta (80-100)
MCH 29.0 pg, interval de referinta (27-33)
MCHC 33.1 g/dL, interval de referinta (32-36)
RDW-SD 42.0 fL, interval de referinta (39-46)
RDW-CV 13.1 %, interval de referinta (11.5-14.5)

Formula leucocitara:
NEUT# 5.73 10^3/uL, interval de referinta (1.56-6.13)
NEUT% 69.8 %, interval de referinta (40-70)
LYMPH# 1.82 10^3/uL, interval de referinta (1.0-4.0)
LYMPH% 22.2 %, interval de referinta (20-45)
MONO# 0.55 10^3/uL, interval de referinta (0.1-0.9)
MONO% 6.7 %, interval de referinta (2-10)
EOS# 0.08 10^3/uL, interval de referinta (0.0-0.5)
EOS% 1.0 %, interval de referinta (0-6)
BASO# 0.02 10^3/uL, interval de referinta (0.0-0.2)
BASO% 0.2 %, interval de referinta (0-1)
PCT 0.28 %, interval de referinta (0.15-0.35)
NRBC# 0.02 10^3/uL, interval de referinta (0.00-0.05)
NRBC% 0.24 %, interval de referinta (0.0-0.5)

Biochimie:
Glicemie 92 mg/dL, interval de referinta (70-110)
Creatinina 0.85 mg/dL, interval de referinta (0.6-1.3)
Acid uric 7.2 mg/dL, interval de referinta (3.5-7.0), valoare crescuta
Feritina 320 ng/mL, interval de referinta (30-400)

MEDICATIE LA EXTERNARE:
Hidroxiuree 500mg, 1 comprimat dimineata si 1 comprimat seara, continuu.
Acid folic 5mg, 1 comprimat pe zi, continuu.
"""

ROMANIAN_DISCHARGE_BILET_DE_EXTERNARE = """
BILET DE EXTERNARE
Spitalul Municipal Test

Pacient: Vasilescu Andrei Test
Data internarii: 02.02.2026
Data externarii: 04.02.2026

Diagnostic la externare: Pneumonie comunitara dreapta.

Epicriza: Pacientul s-a internat pentru febra si tuse productiva. A primit
tratament antibiotic cu evolutie favorabila.

Recomandari la externare: Continuare tratament ambulator, control peste 7
zile.
"""

ROMANIAN_HOSPITAL_ADMISSION_NOTE = """
FOAIE DE INTERNARE
Spitalul Municipal Test
Sectie: Cardiologie

Pacient: Popescu Ion Test
Data internarii: 12.03.2026

Motiv de internare: Durere toracica cu iradiere in bratul stang, dispnee de
efort.
Diagnostic la internare: Sindrom coronarian acut.

Anamneza: Pacientul relateaza debutul simptomatologiei in urma cu 3 ore.
Antecedente personale patologice: HTA, dislipidemie.

Examen clinic la internare: TA 160/95 mmHg, AV 92 bpm, SpO2 96%.

Se interneaza pentru monitorizare si investigatii suplimentare.
"""

ROMANIAN_OUTPATIENT_SCRISOARE_MEDICALA = """
SCRISOARE MEDICALA
Cabinet de specialitate Cardiologie
Dr. Ionescu Radu

Pacient: Georgescu Ana Test
Data consultatiei: 15.03.2026

Motivul consultatiei: Palpitatii intermitente de 2 saptamani.

Anamneza: Pacienta relateaza episoade de palpitatii, fara sincopa.
Antecedente: fara.

Examen clinic: cord in ritm sinusal, fara sufluri.

Consultatie cardiologica de specialitate. Se recomanda Holter ECG 24h si
control peste 2 saptamani in ambulator.

Va rog sa evaluati pacienta si sa continuati investigatiile in ambulator.
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
