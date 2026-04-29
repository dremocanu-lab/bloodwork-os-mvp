from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any


# -----------------------------
# Text normalization
# -----------------------------

def strip_accents(value: str | None) -> str:
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    value = strip_accents(str(value))
    value = value.lower()

    replacements = {
        "ă": "a",
        "â": "a",
        "î": "i",
        "ș": "s",
        "ş": "s",
        "ț": "t",
        "ţ": "t",
        "µ": "u",
        "μ": "u",
        "×": "x",
        "–": "-",
        "—": "-",
        "_": " ",
        ":": " ",
        ";": " ",
        ",": " ",
        "(": " ",
        ")": " ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r"[^a-z0-9%+#./\- ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def compact_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9%#]+", "", normalize_text(value))


def wordish_contains(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False

    if haystack == needle:
        return True

    if compact_key(haystack) == compact_key(needle):
        return True

    if len(needle) >= 3:
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            return True

    return False


# -----------------------------
# Catalog definitions
# -----------------------------

@dataclass(frozen=True)
class LabDefinition:
    canonical_name: str
    category: str
    synonyms: tuple[str, ...]


# Urine intentionally ignored right now.
URINE_KEYWORDS = (
    "urina",
    "urine",
    "urocultura",
    "urine culture",
    "sumar urina",
    "examen urina",
    "sediment urinar",
    "urinary sediment",
    "proteinurie",
    "proteinuria",
    "albuminurie",
    "albuminuria",
    "hematii urinare",
    "leucocite urinare",
    "nitriti",
    "nitrites",
    "urobilinogen",
    "bilirubina urinara",
    "corpi cetonici",
    "ketone",
    "ketones",
    "glucoza urinara",
    "densitate urinara",
    "specific gravity",
    "ph urinar",
)


LAB_DEFINITIONS: list[LabDefinition] = [
    # =========================================================
    # HEMATOLOGIE / CBC
    # =========================================================
    LabDefinition(
        "White Blood Cell Count",
        "Hematologie",
        (
            "wbc", "leu", "leucocite", "leucocytes", "white blood cells",
            "white blood cell count", "numar leucocite", "nr leucocite",
            "leucocite totale", "globule albe", "numar globule albe",
            "celule albe", "white cells",
        ),
    ),
    LabDefinition(
        "Red Blood Cell Count",
        "Hematologie",
        (
            "rbc", "eritrocite", "erythrocytes", "red blood cells",
            "red blood cell count", "hematii", "numar hematii", "nr hematii",
            "numar eritrocite", "nr eritrocite", "globule rosii",
            "numar globule rosii", "red cells",
        ),
    ),
    LabDefinition(
        "Hemoglobin",
        "Hematologie",
        (
            "hgb", "hb", "hemoglobina", "hemoglobin", "haemoglobin",
            "hemoglobina eritrocitara", "conc hemoglobina",
        ),
    ),
    LabDefinition(
        "Hematocrit",
        "Hematologie",
        (
            "hct", "ht", "hematocrit", "haematocrit",
        ),
    ),
    LabDefinition(
        "Mean Corpuscular Volume",
        "Hematologie",
        (
            "mcv", "vem", "volum eritrocitar mediu",
            "mean corpuscular volume", "mean cell volume",
        ),
    ),
    LabDefinition(
        "Mean Corpuscular Hemoglobin",
        "Hematologie",
        (
            "mch", "hem", "hemoglobina eritrocitara medie",
            "hemoglobina medie eritrocitara", "mean corpuscular hemoglobin",
            "mean cell hemoglobin",
        ),
    ),
    LabDefinition(
        "Mean Corpuscular Hemoglobin Concentration",
        "Hematologie",
        (
            "mchc", "chcm", "concentratia medie de hemoglobina",
            "concentratie medie hemoglobina eritrocitara",
            "mean corpuscular hemoglobin concentration",
            "mean cell hemoglobin concentration",
        ),
    ),
    LabDefinition(
        "Red Cell Distribution Width - SD",
        "Hematologie",
        (
            "rdw-sd", "rdw sd", "red cell distribution width sd",
            "largimea distributiei eritrocitare sd",
            "distributie eritrocitara sd",
        ),
    ),
    LabDefinition(
        "Red Cell Distribution Width - CV",
        "Hematologie",
        (
            "rdw-cv", "rdw cv", "red cell distribution width cv",
            "largimea distributiei eritrocitare cv",
            "distributie eritrocitara cv",
        ),
    ),
    LabDefinition(
        "Platelet Count",
        "Hematologie",
        (
            "plt", "plachete", "trombocite", "platelets",
            "platelet count", "numar trombocite", "nr trombocite",
            "numar plachete", "nr plachete",
        ),
    ),
    LabDefinition(
        "Platelet Distribution Width",
        "Hematologie",
        (
            "pdw", "platelet distribution width",
            "largimea distributiei trombocitare",
            "distributie trombocitara",
        ),
    ),
    LabDefinition(
        "Mean Platelet Volume",
        "Hematologie",
        (
            "mpv", "volum trombocitar mediu", "mean platelet volume",
        ),
    ),
    LabDefinition(
        "Plateletcrit",
        "Hematologie",
        (
            "pct", "plateletcrit", "trombocrit", "plachetocrit",
        ),
    ),
    LabDefinition(
        "P-LCR",
        "Hematologie",
        (
            "p-lcr", "plcr", "platelet large cell ratio",
            "raport trombocite mari",
        ),
    ),
    LabDefinition(
        "P-LCC",
        "Hematologie",
        (
            "p-lcc", "plcc", "platelet large cell count",
        ),
    ),
    LabDefinition(
        "Nucleated Red Blood Cells Absolute",
        "Hematologie",
        (
            "nrbc#", "nrbc #", "nrbc absolute", "nrbc abs",
            "nucleated red blood cells absolute",
            "eritrocite nucleate absolute", "hematii nucleate absolute",
        ),
    ),
    LabDefinition(
        "NRBC Percent",
        "Hematologie",
        (
            "nrbc%", "nrbc %", "nrbc percent", "nrbc procent",
            "nucleated red blood cells percent",
            "eritrocite nucleate procent", "hematii nucleate procent",
        ),
    ),
    LabDefinition(
        "Neutrophils Absolute",
        "Hematologie",
        (
            "neut#", "neut #", "neut abs", "neutrofile absolute",
            "neutrophils absolute", "neutrophil absolute count",
            "granulocite neutrofile absolute",
        ),
    ),
    LabDefinition(
        "Neutrophils Percent",
        "Hematologie",
        (
            "neut%", "neut %", "neutrofile procent", "neutrofile %",
            "neutrophils percent", "neutrophils %",
            "granulocite neutrofile procent",
        ),
    ),
    LabDefinition(
        "Lymphocytes Absolute",
        "Hematologie",
        (
            "lymph#", "lymph #", "lymph abs", "limfocite absolute",
            "lymphocytes absolute", "lymphocyte absolute count",
        ),
    ),
    LabDefinition(
        "Lymphocytes Percent",
        "Hematologie",
        (
            "lymph%", "lymph %", "limfocite procent", "limfocite %",
            "lymphocytes percent", "lymphocytes %",
        ),
    ),
    LabDefinition(
        "Monocytes Absolute",
        "Hematologie",
        (
            "mono#", "mono #", "mono abs", "monocite absolute",
            "monocytes absolute", "monocyte absolute count",
        ),
    ),
    LabDefinition(
        "Monocytes Percent",
        "Hematologie",
        (
            "mono%", "mono %", "monocite procent", "monocite %",
            "monocytes percent", "monocytes %",
        ),
    ),
    LabDefinition(
        "Eosinophils Absolute",
        "Hematologie",
        (
            "eo#", "eo #", "eos#", "eos #", "eosinofile absolute",
            "eozinofile absolute", "eosinophils absolute",
            "eosinophil absolute count",
        ),
    ),
    LabDefinition(
        "Eosinophils Percent",
        "Hematologie",
        (
            "eo%", "eo %", "eos%", "eos %", "eosinofile procent",
            "eozinofile procent", "eosinophils percent", "eosinophils %",
        ),
    ),
    LabDefinition(
        "Basophils Absolute",
        "Hematologie",
        (
            "baso#", "baso #", "baso abs", "bazofile absolute",
            "basofile absolute", "basophils absolute",
            "basophil absolute count",
        ),
    ),
    LabDefinition(
        "Basophils Percent",
        "Hematologie",
        (
            "baso%", "baso %", "bazofile procent", "basofile procent",
            "basophils percent", "basophils %",
        ),
    ),
    LabDefinition(
        "Immature Granulocytes Absolute",
        "Hematologie",
        (
            "ig#", "ig #", "ig abs", "granulocite imature absolute",
            "immature granulocytes absolute",
        ),
    ),
    LabDefinition(
        "Immature Granulocytes Percent",
        "Hematologie",
        (
            "ig%", "ig %", "granulocite imature procent",
            "granulocite imature %", "immature granulocytes percent",
        ),
    ),
    LabDefinition(
        "Reticulocytes Percent",
        "Hematologie",
        (
            "ret%", "ret %", "reticulocite procent",
            "reticulocite %", "reticulocytes percent",
        ),
    ),
    LabDefinition(
        "Reticulocytes Absolute",
        "Hematologie",
        (
            "ret#", "ret #", "reticulocite absolute",
            "reticulocytes absolute", "reticulocyte count",
        ),
    ),
    LabDefinition(
        "ESR",
        "Hematologie",
        (
            "vsh", "esr", "viteza de sedimentare a hematiilor",
            "erythrocyte sedimentation rate", "sedimentation rate",
        ),
    ),

    # =========================================================
    # COAGULARE
    # =========================================================
    LabDefinition(
        "Prothrombin Time",
        "Coagulare",
        (
            "pt", "timp de protrombina", "prothrombin time",
            "quick", "timp quick",
        ),
    ),
    LabDefinition("INR", "Coagulare", ("inr", "international normalized ratio")),
    LabDefinition(
        "APTT",
        "Coagulare",
        (
            "aptt", "a ptt", "timp de tromboplastina partial activata",
            "activated partial thromboplastin time",
        ),
    ),
    LabDefinition(
        "Fibrinogen",
        "Coagulare",
        (
            "fibrinogen", "fibrinogenemie", "fibrinogen plasma",
        ),
    ),
    LabDefinition(
        "D-Dimer",
        "Coagulare",
        (
            "d dimer", "d-dimer", "ddimer", "dimeri d",
            "dimer d", "d dimeri",
        ),
    ),
    LabDefinition(
        "Thrombin Time",
        "Coagulare",
        (
            "tt", "timp trombina", "thrombin time",
        ),
    ),
    LabDefinition(
        "Antithrombin III",
        "Coagulare",
        (
            "antitrombina iii", "antithrombin iii", "at iii",
        ),
    ),
    LabDefinition(
        "Protein C",
        "Coagulare",
        (
            "proteina c", "protein c",
        ),
    ),
    LabDefinition(
        "Protein S",
        "Coagulare",
        (
            "proteina s", "protein s",
        ),
    ),

    # =========================================================
    # BIOCHIMIE GENERALA
    # =========================================================
    LabDefinition(
        "Glucose",
        "Biochimie generala",
        (
            "glucoza", "glucose", "glicemie", "glycemia",
            "blood glucose", "serum glucose", "glucoza serica",
        ),
    ),
    LabDefinition(
        "HbA1c",
        "Biochimie generala",
        (
            "hba1c", "hemoglobina glicata", "hemoglobina glicozilata",
            "glycated hemoglobin", "glycosylated hemoglobin",
        ),
    ),
    LabDefinition(
        "Urea",
        "Biochimie generala",
        (
            "uree", "urea", "blood urea", "uree serica",
            "azot ureic", "bun", "blood urea nitrogen",
        ),
    ),
    LabDefinition(
        "Creatinine",
        "Biochimie generala",
        (
            "creatinina", "creatinine", "creatinina serica",
            "serum creatinine",
        ),
    ),
    LabDefinition(
        "eGFR",
        "Biochimie generala",
        (
            "egfr", "e gfr", "rfg", "rata filtrarii glomerulare",
            "filtrare glomerulara", "estimated glomerular filtration rate",
        ),
    ),
    LabDefinition(
        "Uric Acid",
        "Biochimie generala",
        (
            "acid uric", "uric acid", "uricemie",
        ),
    ),
    LabDefinition(
        "Total Protein",
        "Biochimie generala",
        (
            "proteine totale", "total protein", "total proteins",
            "proteinemie totala",
        ),
    ),
    LabDefinition(
        "Albumin",
        "Biochimie generala",
        (
            "albumina", "albumin", "albumina serica", "serum albumin",
        ),
    ),
    LabDefinition(
        "Calcium",
        "Biochimie generala",
        (
            "calciu", "calcium", "ca", "calciu seric", "serum calcium",
        ),
    ),
    LabDefinition(
        "Ionized Calcium",
        "Biochimie generala",
        (
            "calciu ionic", "calciu ionizat", "ionized calcium",
            "calcium ionizat",
        ),
    ),
    LabDefinition(
        "Magnesium",
        "Biochimie generala",
        (
            "magneziu", "magnesium", "mg", "magneziu seric",
        ),
    ),
    LabDefinition(
        "Phosphorus",
        "Biochimie generala",
        (
            "fosfor", "phosphorus", "phosphate", "fosfat",
            "fosfor seric",
        ),
    ),
    LabDefinition(
        "Sodium",
        "Biochimie generala",
        (
            "sodiu", "sodium", "na", "natriu", "serum sodium",
        ),
    ),
    LabDefinition(
        "Potassium",
        "Biochimie generala",
        (
            "potasiu", "potassium", "k", "kalium", "serum potassium",
        ),
    ),
    LabDefinition(
        "Chloride",
        "Biochimie generala",
        (
            "clor", "cloruri", "chloride", "cl", "serum chloride",
        ),
    ),
    LabDefinition(
        "Bicarbonate",
        "Biochimie generala",
        (
            "bicarbonat", "bicarbonate", "hco3", "co2 total",
        ),
    ),
    LabDefinition(
        "Iron",
        "Biochimie generala",
        (
            "fier", "iron", "sideremie", "serum iron",
            "fier seric",
        ),
    ),
    LabDefinition(
        "Ferritin",
        "Biochimie generala",
        (
            "feritina", "ferritin", "serum ferritin",
        ),
    ),
    LabDefinition(
        "Transferrin",
        "Biochimie generala",
        (
            "transferina", "transferrin",
        ),
    ),
    LabDefinition(
        "TIBC",
        "Biochimie generala",
        (
            "tibc", "capacitate totala de legare a fierului",
            "total iron binding capacity",
        ),
    ),
    LabDefinition(
        "Transferrin Saturation",
        "Biochimie generala",
        (
            "saturatia transferinei", "transferrin saturation",
            "tsat", "sat transferina",
        ),
    ),
    LabDefinition(
        "Vitamin B12",
        "Biochimie generala",
        (
            "vitamina b12", "b12", "cobalamina", "vitamin b12",
        ),
    ),
    LabDefinition(
        "Folate",
        "Biochimie generala",
        (
            "folat", "folate", "acid folic", "folic acid",
        ),
    ),
    LabDefinition(
        "Vitamin D",
        "Biochimie generala",
        (
            "vitamina d", "vitamin d", "25 oh vitamina d",
            "25-oh vitamin d", "25 hydroxy vitamin d",
            "25 hidroxivitamina d", "25 oh d",
        ),
    ),

    # Liver enzymes / pancreatic enzymes / lipids
    LabDefinition("ALT", "Biochimie generala", ("alt", "alat", "gpt", "tgp", "alanin aminotransferaza", "alanine aminotransferase")),
    LabDefinition("AST", "Biochimie generala", ("ast", "asat", "got", "tgo", "aspartat aminotransferaza", "aspartate aminotransferase")),
    LabDefinition("GGT", "Biochimie generala", ("ggt", "gama gt", "gamma gt", "gama glutamil transferaza", "gamma glutamyl transferase")),
    LabDefinition("Alkaline Phosphatase", "Biochimie generala", ("fosfataza alcalina", "alkaline phosphatase", "alp", "fal")),
    LabDefinition("LDH", "Biochimie generala", ("ldh", "lactat dehidrogenaza", "lactate dehydrogenase")),
    LabDefinition("CK", "Biochimie generala", ("ck", "cpk", "creatin kinaza", "creatine kinase", "creatin phosphokinase")),
    LabDefinition("CK-MB", "Biochimie generala", ("ck mb", "ck-mb", "creatin kinaza mb", "creatine kinase mb")),
    LabDefinition("Amylase", "Biochimie generala", ("amilaza", "amylase", "amilaza serica")),
    LabDefinition("Lipase", "Biochimie generala", ("lipaza", "lipase")),
    LabDefinition("Total Bilirubin", "Biochimie generala", ("bilirubina totala", "total bilirubin")),
    LabDefinition("Direct Bilirubin", "Biochimie generala", ("bilirubina directa", "direct bilirubin", "conjugated bilirubin")),
    LabDefinition("Indirect Bilirubin", "Biochimie generala", ("bilirubina indirecta", "indirect bilirubin", "unconjugated bilirubin")),
    LabDefinition("Total Cholesterol", "Biochimie generala", ("colesterol total", "total cholesterol", "cholesterol total")),
    LabDefinition("HDL Cholesterol", "Biochimie generala", ("hdl", "hdl colesterol", "hdl cholesterol", "colesterol hdl")),
    LabDefinition("LDL Cholesterol", "Biochimie generala", ("ldl", "ldl colesterol", "ldl cholesterol", "colesterol ldl")),
    LabDefinition("VLDL Cholesterol", "Biochimie generala", ("vldl", "vldl colesterol", "vldl cholesterol")),
    LabDefinition("Triglycerides", "Biochimie generala", ("trigliceride", "triglycerides", "tg")),
    LabDefinition("Apolipoprotein A1", "Biochimie generala", ("apolipoproteina a1", "apoa1", "apo a1", "apolipoprotein a1")),
    LabDefinition("Apolipoprotein B", "Biochimie generala", ("apolipoproteina b", "apob", "apo b", "apolipoprotein b")),
    LabDefinition("Lipoprotein(a)", "Biochimie generala", ("lipoproteina a", "lipoprotein a", "lp a", "lp(a)")),

    # =========================================================
    # IMUNOLOGIE / SEROLOGIE / INFLAMMATIE
    # =========================================================
    LabDefinition("CRP", "Imunologie", ("crp", "proteina c reactiva", "c reactive protein")),
    LabDefinition("High Sensitivity CRP", "Imunologie", ("hs crp", "hs-crp", "crp ultrasensibil", "crp inalta sensibilitate", "high sensitivity crp")),
    LabDefinition("Procalcitonin", "Imunologie", ("procalcitonina", "procalcitonin", "pct procalcitonin")),
    LabDefinition("Rheumatoid Factor", "Imunologie", ("factor reumatoid", "rheumatoid factor", "rf")),
    LabDefinition("Anti-CCP", "Imunologie", ("anti ccp", "anti-ccp", "anticorpi anti ccp", "ccp antibodies")),
    LabDefinition("ANA", "Imunologie", ("ana", "anticorpi antinucleari", "antinuclear antibodies")),
    LabDefinition("Anti-dsDNA", "Imunologie", ("anti dsdna", "anti-dsdna", "anticorpi anti adn dublu catenar", "double stranded dna antibodies")),
    LabDefinition("IgA", "Imunologie", ("iga", "imunoglobulina a", "immunoglobulin a")),
    LabDefinition("IgG", "Imunologie", ("igg", "imunoglobulina g", "immunoglobulin g")),
    LabDefinition("IgM", "Imunologie", ("igm", "imunoglobulina m", "immunoglobulin m")),
    LabDefinition("IgE", "Imunologie", ("ige", "imunoglobulina e", "immunoglobulin e")),
    LabDefinition("C3 Complement", "Imunologie", ("c3", "complement c3")),
    LabDefinition("C4 Complement", "Imunologie", ("c4", "complement c4")),
    LabDefinition("HBsAg", "Imunologie", ("hbsag", "antigen hbs", "hepatita b antigen de suprafata", "hepatitis b surface antigen")),
    LabDefinition("Anti-HBs", "Imunologie", ("anti hbs", "anti-hbs", "anticorpi anti hbs", "hepatitis b surface antibody")),
    LabDefinition("Anti-HBc", "Imunologie", ("anti hbc", "anti-hbc", "anticorpi anti hbc", "hepatitis b core antibody")),
    LabDefinition("Anti-HCV", "Imunologie", ("anti hcv", "anti-hcv", "anticorpi anti hcv", "hepatitis c antibody")),
    LabDefinition("HIV Ag/Ab", "Imunologie", ("hiv", "hiv ag ab", "hiv 1 2", "hiv combo", "hiv antigen anticorp", "hiv antigen antibody")),
    LabDefinition("VDRL", "Imunologie", ("vdrl", "rpr", "sifilis", "syphilis")),
    LabDefinition("TPHA", "Imunologie", ("tpha", "tppa", "treponema pallidum")),
    LabDefinition("Toxoplasma IgG", "Imunologie", ("toxoplasma igg", "toxoplasma gondii igg")),
    LabDefinition("Toxoplasma IgM", "Imunologie", ("toxoplasma igm", "toxoplasma gondii igm")),
    LabDefinition("Rubella IgG", "Imunologie", ("rubella igg", "rubeola igg")),
    LabDefinition("Rubella IgM", "Imunologie", ("rubella igm", "rubeola igm")),
    LabDefinition("CMV IgG", "Imunologie", ("cmv igg", "citomegalovirus igg", "cytomegalovirus igg")),
    LabDefinition("CMV IgM", "Imunologie", ("cmv igm", "citomegalovirus igm", "cytomegalovirus igm")),
    LabDefinition("EBV VCA IgG", "Imunologie", ("ebv vca igg", "epstein barr vca igg")),
    LabDefinition("EBV VCA IgM", "Imunologie", ("ebv vca igm", "epstein barr vca igm")),

    # =========================================================
    # ENDOCRINOLOGIE / HORMONI
    # =========================================================
    LabDefinition("TSH", "Endocrinologie", ("tsh", "tirotropina", "thyroid stimulating hormone")),
    LabDefinition("Free T4", "Endocrinologie", ("ft4", "free t4", "t4 liber", "tiroxina libera")),
    LabDefinition("Free T3", "Endocrinologie", ("ft3", "free t3", "t3 liber", "triiodotironina libera")),
    LabDefinition("Total T4", "Endocrinologie", ("t4 total", "total t4", "tiroxina totala")),
    LabDefinition("Total T3", "Endocrinologie", ("t3 total", "total t3", "triiodotironina totala")),
    LabDefinition("Anti-TPO", "Endocrinologie", ("anti tpo", "anti-tpo", "anticorpi anti tpo", "thyroid peroxidase antibodies")),
    LabDefinition("Anti-Thyroglobulin", "Endocrinologie", ("anti tiroglobulina", "anti-thyroglobulin", "anti tg", "anticorpi anti tiroglobulina")),
    LabDefinition("TRAb", "Endocrinologie", ("trab", "anti receptor tsh", "tsh receptor antibodies")),
    LabDefinition("PTH", "Endocrinologie", ("pth", "parathormon", "parathyroid hormone")),
    LabDefinition("Cortisol", "Endocrinologie", ("cortizol", "cortisol")),
    LabDefinition("ACTH", "Endocrinologie", ("acth", "adrenocorticotrop", "adrenocorticotropic hormone")),
    LabDefinition("Insulin", "Endocrinologie", ("insulina", "insulin")),
    LabDefinition("C-Peptide", "Endocrinologie", ("c peptid", "c-peptide", "peptid c")),
    LabDefinition("FSH", "Endocrinologie", ("fsh", "follicle stimulating hormone", "hormon foliculostimulant")),
    LabDefinition("LH", "Endocrinologie", ("lh", "luteinizing hormone", "hormon luteinizant")),
    LabDefinition("Estradiol", "Endocrinologie", ("estradiol", "e2", "estradiol seric")),
    LabDefinition("Progesterone", "Endocrinologie", ("progesteron", "progesterone")),
    LabDefinition("Prolactin", "Endocrinologie", ("prolactina", "prolactin")),
    LabDefinition("Testosterone", "Endocrinologie", ("testosteron", "testosterone", "testosteron total", "total testosterone")),
    LabDefinition("Free Testosterone", "Endocrinologie", ("testosteron liber", "free testosterone")),
    LabDefinition("DHEA-S", "Endocrinologie", ("dhea s", "dhea-s", "dehidroepiandrosteron sulfat", "dehydroepiandrosterone sulfate")),
    LabDefinition("SHBG", "Endocrinologie", ("shbg", "sex hormone binding globulin")),
    LabDefinition("17-OH Progesterone", "Endocrinologie", ("17 oh progesteron", "17-oh progesterone", "17 hydroxyprogesterone")),
    LabDefinition("Aldosterone", "Endocrinologie", ("aldosteron", "aldosterone")),
    LabDefinition("Renin", "Endocrinologie", ("renina", "renin")),
    LabDefinition("Growth Hormone", "Endocrinologie", ("hormon de crestere", "growth hormone", "gh", "somatotrop")),
    LabDefinition("IGF-1", "Endocrinologie", ("igf 1", "igf-1", "insulin like growth factor 1")),

    # =========================================================
    # MARKERI TUMORALI
    # =========================================================
    LabDefinition("PSA Total", "Markeri tumorali", ("psa total", "total psa", "antigen specific prostatic total")),
    LabDefinition("PSA Free", "Markeri tumorali", ("psa liber", "free psa", "psa free")),
    LabDefinition("CEA", "Markeri tumorali", ("cea", "antigen carcinoembrionar", "carcinoembryonic antigen")),
    LabDefinition("CA 19-9", "Markeri tumorali", ("ca 19 9", "ca19-9", "ca 19-9")),
    LabDefinition("CA 125", "Markeri tumorali", ("ca 125", "ca-125")),
    LabDefinition("CA 15-3", "Markeri tumorali", ("ca 15 3", "ca15-3", "ca 15-3")),
    LabDefinition("AFP", "Markeri tumorali", ("afp", "alfa fetoproteina", "alpha fetoprotein")),
    LabDefinition("Beta-hCG", "Markeri tumorali", ("beta hcg", "beta-hcg", "hcg beta", "gonadotropina corionica beta")),
    LabDefinition("NSE", "Markeri tumorali", ("nse", "neuron specific enolase", "enolaza neuron specifica")),
    LabDefinition("CYFRA 21-1", "Markeri tumorali", ("cyfra 21 1", "cyfra 21-1")),
    LabDefinition("HE4", "Markeri tumorali", ("he4", "human epididymis protein 4")),

    # =========================================================
    # BIOLOGIE MOLECULARA GENERALA
    # =========================================================
    LabDefinition("SARS-CoV-2 RNA", "Biologie moleculara generala", ("sars cov 2", "sars-cov-2", "covid pcr", "covid rt pcr", "arn sars cov 2", "sars cov 2 rna")),
    LabDefinition("Influenza A RNA", "Biologie moleculara generala", ("influenza a", "virus gripal a", "arn influenza a", "influenza a rna")),
    LabDefinition("Influenza B RNA", "Biologie moleculara generala", ("influenza b", "virus gripal b", "arn influenza b", "influenza b rna")),
    LabDefinition("RSV RNA", "Biologie moleculara generala", ("rsv", "virus sincitial respirator", "respiratory syncytial virus", "rsv rna")),
    LabDefinition("HBV DNA", "Biologie moleculara generala", ("hbv dna", "adn hbv", "viremie hbv", "hepatita b adn", "hepatitis b dna")),
    LabDefinition("HCV RNA", "Biologie moleculara generala", ("hcv rna", "arn hcv", "viremie hcv", "hepatita c arn", "hepatitis c rna")),
    LabDefinition("HIV RNA", "Biologie moleculara generala", ("hiv rna", "arn hiv", "viremie hiv", "hiv viral load")),
    LabDefinition("HPV DNA", "Biologie moleculara generala", ("hpv dna", "adn hpv", "genotipare hpv", "hpv genotyping", "hpv high risk")),
    LabDefinition("Chlamydia trachomatis DNA", "Biologie moleculara generala", ("chlamydia trachomatis", "ct dna", "adn chlamydia", "chlamydia dna")),
    LabDefinition("Neisseria gonorrhoeae DNA", "Biologie moleculara generala", ("neisseria gonorrhoeae", "ng dna", "adn gonoree", "gonorrhea dna", "gonococ dna")),
    LabDefinition("Mycoplasma genitalium DNA", "Biologie moleculara generala", ("mycoplasma genitalium", "mg dna", "mycoplasma genitalium dna")),
    LabDefinition("Ureaplasma urealyticum DNA", "Biologie moleculara generala", ("ureaplasma urealyticum", "uu dna", "ureaplasma dna")),
    LabDefinition("Mycobacterium tuberculosis PCR", "Biologie moleculara generala", ("mycobacterium tuberculosis", "tb pcr", "mtb pcr", "tuberculoza pcr", "tuberculosis pcr")),
    LabDefinition("Factor V Leiden", "Biologie moleculara generala", ("factor v leiden", "f5 leiden", "mutatia factor v leiden")),
    LabDefinition("Prothrombin G20210A", "Biologie moleculara generala", ("factor ii", "protrombina g20210a", "prothrombin g20210a", "mutatia protrombinei")),
    LabDefinition("MTHFR C677T", "Biologie moleculara generala", ("mthfr c677t", "mutatia mthfr c677t")),
    LabDefinition("MTHFR A1298C", "Biologie moleculara generala", ("mthfr a1298c", "mutatia mthfr a1298c")),
    LabDefinition("HLA-B27", "Biologie moleculara generala", ("hla b27", "hla-b27")),
    LabDefinition("BRCA1", "Biologie moleculara generala", ("brca1", "brca 1")),
    LabDefinition("BRCA2", "Biologie moleculara generala", ("brca2", "brca 2")),
    LabDefinition("JAK2 V617F", "Biologie moleculara generala", ("jak2", "jak2 v617f", "mutatia jak2")),
    LabDefinition("BCR-ABL", "Biologie moleculara generala", ("bcr abl", "bcr-abl", "transcript bcr abl")),
    LabDefinition("EGFR Mutation", "Biologie moleculara generala", ("egfr mutatie", "egfr mutation")),
    LabDefinition("KRAS Mutation", "Biologie moleculara generala", ("kras mutatie", "kras mutation")),
    LabDefinition("NRAS Mutation", "Biologie moleculara generala", ("nras mutatie", "nras mutation")),
    LabDefinition("BRAF Mutation", "Biologie moleculara generala", ("braf mutatie", "braf mutation", "braf v600e")),

    # =========================================================
    # MICROBIOLOGIE
    # =========================================================
    LabDefinition("Blood Culture", "Microbiologie", ("hemocultura", "blood culture", "blood cultures")),
    LabDefinition("Throat Culture", "Microbiologie", ("exsudat faringian", "throat culture", "pharyngeal culture")),
    LabDefinition("Nasal Culture", "Microbiologie", ("exsudat nazal", "nasal culture")),
    LabDefinition("Wound Culture", "Microbiologie", ("cultura secretie plaga", "wound culture", "plaga cultura")),
    LabDefinition("Sputum Culture", "Microbiologie", ("cultura sputa", "sputum culture", "sputa")),
    LabDefinition("Stool Culture", "Microbiologie", ("coprocultura", "stool culture", "fecal culture")),
    LabDefinition("Antibiogram", "Microbiologie", ("antibiograma", "antibiogram", "susceptibilitate antibiotice", "antimicrobial susceptibility")),
    LabDefinition("Clostridioides difficile toxin", "Microbiologie", ("clostridium difficile", "clostridioides difficile", "toxina a b", "c difficile toxin")),
    LabDefinition("Helicobacter pylori Antigen", "Microbiologie", ("helicobacter pylori antigen", "h pylori antigen", "antigen helicobacter")),
    LabDefinition("Candida Culture", "Microbiologie", ("candida", "cultura candida", "candida culture")),
]


CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Hematologie": (
        "hematologie", "hemograma", "hemoleucograma", "cbc", "blood count",
        "citomorfologie", "leucocite", "eritrocite", "hematii", "trombocite",
        "reticulocite",
    ),
    "Coagulare": (
        "coagulare", "coagulograma", "hemostaza", "inr", "aptt", "protrombina",
        "fibrinogen", "d dimer", "d-dimer",
    ),
    "Biochimie generala": (
        "biochimie", "biochimie generala", "chimie clinica", "clinical chemistry",
        "enzime", "lipide", "glicemie", "glucoza", "creatinina", "uree",
        "colesterol", "trigliceride", "bilirubina", "transaminaze",
    ),
    "Imunologie": (
        "imunologie", "serologie", "anticorpi", "antigen", "immunology",
        "serology", "crp", "imunoglobuline", "immunoglobulin",
    ),
    "Endocrinologie": (
        "endocrinologie", "hormoni", "hormones", "tiroida", "thyroid",
        "tsh", "ft4", "ft3", "cortizol", "insulina", "testosteron",
    ),
    "Markeri tumorali": (
        "markeri tumorali", "tumor markers", "tumour markers",
        "psa", "cea", "ca 19", "ca125", "afp",
    ),
    "Biologie moleculara generala": (
        "biologie moleculara", "molecular biology", "pcr", "rt pcr",
        "dna", "adn", "rna", "arn", "genotipare", "genotyping",
        "mutatie", "mutation", "viral load", "viremie",
    ),
    "Microbiologie": (
        "microbiologie", "microbiology", "cultura", "culture",
        "culturi", "antibiograma", "antibiogram", "exsudat",
        "hemocultura", "coprocultura", "sputa",
    ),
}


CATEGORY_ORDER = [
    "Hematologie",
    "Coagulare",
    "Biochimie generala",
    "Endocrinologie",
    "Imunologie",
    "Markeri tumorali",
    "Biologie moleculara generala",
    "Microbiologie",
    "Alte analize",
]


# -----------------------------
# Matching / normalization
# -----------------------------

def is_urine_related(raw_name: str | None, context_text: str | None = None) -> bool:
    combined = normalize_text(f"{raw_name or ''} {context_text or ''}")
    return any(normalize_text(keyword) in combined for keyword in URINE_KEYWORDS)


def find_lab_definition(raw_name: str | None) -> LabDefinition | None:
    normalized = normalize_text(raw_name)
    compact = compact_key(raw_name)

    if not normalized:
        return None

    best_match: LabDefinition | None = None
    best_score = 0

    for definition in LAB_DEFINITIONS:
        candidates = (definition.canonical_name, *definition.synonyms)

        for candidate in candidates:
            candidate_normalized = normalize_text(candidate)
            candidate_compact = compact_key(candidate)

            if not candidate_normalized:
                continue

            score = 0

            if normalized == candidate_normalized:
                score = 100
            elif compact and compact == candidate_compact:
                score = 98
            elif wordish_contains(normalized, candidate_normalized):
                score = 90
            elif len(candidate_normalized) >= 4 and candidate_normalized in normalized:
                score = 75
            elif len(normalized) >= 4 and normalized in candidate_normalized:
                score = 65

            if score > best_score:
                best_score = score
                best_match = definition

    return best_match


def infer_category_from_context(*values: str | None) -> str | None:
    combined = normalize_text(" ".join(value for value in values if value))

    if not combined:
        return None

    if any(normalize_text(keyword) in combined for keyword in URINE_KEYWORDS):
        return None

    best_category: str | None = None
    best_score = 0

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            normalized_keyword = normalize_text(keyword)

            if not normalized_keyword:
                continue

            score = 0

            if wordish_contains(combined, normalized_keyword):
                score = 90
            elif normalized_keyword in combined:
                score = 70

            if score > best_score:
                best_score = score
                best_category = category

    return best_category


def clean_raw_name(row: dict[str, Any]) -> str:
    possible_keys = (
        "raw_name",
        "test_name",
        "canonical_name",
        "name",
        "analysis",
        "analyte",
        "denumire",
        "denumire_analiza",
        "test",
        "parameter",
        "parametru",
    )

    for key in possible_keys:
        value = row.get(key)
        if value:
            return str(value).strip()

    return ""


def normalize_lab_row(row: dict[str, Any], context_text: str | None = None) -> dict[str, Any] | None:
    raw_name = clean_raw_name(row)

    if not raw_name:
        return None

    # Skip urine for now, per request.
    if is_urine_related(raw_name):
        return None

    definition = find_lab_definition(raw_name)

    context_category = infer_category_from_context(
        context_text,
        row.get("section"),
        row.get("category"),
        row.get("group"),
        row.get("panel"),
        row.get("chapter"),
        row.get("heading"),
        row.get("source_section"),
    )

    category = definition.category if definition else context_category
    canonical_name = definition.canonical_name if definition else raw_name

    if not category:
        category = "Alte analize"

    cleaned = dict(row)
    cleaned["raw_name"] = raw_name
    cleaned["test_name"] = canonical_name
    cleaned["canonical_name"] = canonical_name
    cleaned["category"] = category

    return cleaned


def normalize_lab_rows(rows: list[dict[str, Any]], context_text: str | None = None) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []

    for row in rows or []:
        normalized = normalize_lab_row(row, context_text=context_text)
        if normalized:
            normalized_rows.append(normalized)

    return normalized_rows


def get_detected_categories(rows: list[dict[str, Any]]) -> list[str]:
    categories: list[str] = []

    for row in rows or []:
        category = row.get("category") or "Alte analize"

        if category not in categories:
            categories.append(category)

    return sorted(
        categories,
        key=lambda category: CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else 999,
    )


def group_rows_by_category(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows or []:
        category = row.get("category") or "Alte analize"
        grouped.setdefault(category, []).append(row)

    return {
        category: grouped[category]
        for category in sorted(
            grouped.keys(),
            key=lambda item: CATEGORY_ORDER.index(item) if item in CATEGORY_ORDER else 999,
        )
    }


# -----------------------------
# Report naming
# -----------------------------

def parse_date_for_title(*values: str | None) -> datetime | None:
    formats = (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
    )

    for value in values:
        if not value:
            continue

        cleaned = str(value).strip()

        for fmt in formats:
            try:
                parsed = datetime.strptime(cleaned, fmt)
                return parsed.replace(tzinfo=None)
            except ValueError:
                pass

        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass

    return None


def format_report_datetime(*values: str | None) -> str:
    parsed = parse_date_for_title(*values)
    if not parsed:
        return datetime.now().strftime("%d/%m/%Y %H:%M")

    return parsed.strftime("%d/%m/%Y %H:%M")


def build_report_name_from_categories(
    rows: list[dict[str, Any]],
    *,
    collected_on: str | None = None,
    test_date: str | None = None,
    reported_on: str | None = None,
    registered_on: str | None = None,
    generated_on: str | None = None,
    created_at: str | None = None,
    fallback_name: str = "Analize medicale",
) -> str:
    categories = get_detected_categories(rows)

    if not categories:
        base = fallback_name
    elif len(categories) == 1:
        base = categories[0]
    elif len(categories) == 2:
        base = f"{categories[0]} & {categories[1]}"
    else:
        base = f"{', '.join(categories[:-1])} & {categories[-1]}"

    date_label = format_report_datetime(
        collected_on,
        test_date,
        reported_on,
        registered_on,
        generated_on,
        created_at,
    )

    return f"{base} {date_label}"


def extract_category_from_raw_text(raw_text: str | None) -> str | None:
    return infer_category_from_context(raw_text)