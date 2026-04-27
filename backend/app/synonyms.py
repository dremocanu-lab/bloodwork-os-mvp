import re


LAB_SYNONYMS = {
    "rbc_he": {
        "display_name": "RBC-HE",
        "category": "cbc_reticulocytes",
        "synonyms": ["rbc-he"],
    },
    "hypo_he": {
        "display_name": "HYPO-HE",
        "category": "cbc_reticulocytes",
        "synonyms": ["hypo-he"],
    },
    "hyper_he": {
        "display_name": "HYPER-HE",
        "category": "cbc_reticulocytes",
        "synonyms": ["hyper-he"],
    },
    "delta_he": {
        "display_name": "DELTA-HE",
        "category": "cbc_reticulocytes",
        "synonyms": ["delta-he"],
    },
    "wbc": {
        "display_name": "White Blood Cell Count",
        "category": "cbc",
        "synonyms": [
            "wbc",
            "white blood cell count",
            "white cell count",
            "total leucocyte count",
            "total leukocyte count",
            "tlc",
            "leucocite",
            "leukocite",
            "numar leucocite",
            "număr leucocite",
        ],
    },
    "rbc": {
        "display_name": "Red Blood Cell Count",
        "category": "cbc",
        "synonyms": [
            "rbc",
            "rbc count",
            "red blood cell count",
            "total rbc count",
            "eritrocite",
            "numar eritrocite",
            "număr eritrocite",
        ],
    },
    "hemoglobin": {
        "display_name": "Hemoglobin",
        "category": "cbc",
        "synonyms": [
            "hemoglobin",
            "haemoglobin",
            "hb",
            "hgb",
            "hemoglobina",
            "hemoglobină",
        ],
    },
    "hematocrit": {
        "display_name": "Hematocrit",
        "category": "cbc",
        "synonyms": [
            "hematocrit",
            "haematocrit",
            "hct",
            "ht",
            "pcv",
            "packed cell volume",
        ],
    },
    "mcv": {
        "display_name": "MCV",
        "category": "cbc",
        "synonyms": ["mcv", "mean corpuscular volume", "vem", "volum eritrocitar mediu"],
    },
    "mch": {
        "display_name": "MCH",
        "category": "cbc",
        "synonyms": ["mch", "hemoglobina eritrocitara medie", "hemoglobină eritrocitară medie"],
    },
    "mchc": {
        "display_name": "MCHC",
        "category": "cbc",
        "synonyms": [
            "mchc",
            "concentratia medie a hemoglobinei eritrocitare",
            "concentrația medie a hemoglobinei eritrocitare",
        ],
    },
    "platelet_count": {
        "display_name": "Platelet Count",
        "category": "cbc",
        "synonyms": [
            "plt",
            "platelet count",
            "platelets",
            "platelet",
            "trombocite",
            "numar trombocite",
            "număr trombocite",
        ],
    },
    "rdw_sd": {
        "display_name": "RDW-SD",
        "category": "cbc",
        "synonyms": ["rdw-sd", "rdw sd"],
    },
    "rdw_cv": {
        "display_name": "RDW-CV",
        "category": "cbc",
        "synonyms": ["rdw-cv", "rdw cv", "rdw"],
    },
    "pdw": {
        "display_name": "PDW",
        "category": "cbc_platelets",
        "synonyms": ["pdw", "platelet distribution width", "latimea distributiei trombocitare"],
    },
    "mpv": {
        "display_name": "MPV",
        "category": "cbc_platelets",
        "synonyms": ["mpv", "mean platelet volume", "volum trombocitar mediu"],
    },
    "p_lcr": {
        "display_name": "P-LCR",
        "category": "cbc_platelets",
        "synonyms": ["p-lcr", "plcr"],
    },
    "pct": {
        "display_name": "PCT",
        "category": "cbc_platelets",
        "synonyms": ["pct", "plateletcrit", "trombocrit"],
    },
    "nrbc_absolute": {
        "display_name": "NRBC Absolute",
        "category": "cbc",
        "synonyms": ["nrbc#", "nrbc absolute"],
    },
    "nrbc_percent": {
        "display_name": "NRBC %",
        "category": "cbc",
        "synonyms": ["nrbc%", "nrbc percent"],
    },
    "neutrophils_absolute": {
        "display_name": "Neutrophils Absolute",
        "category": "cbc_diff",
        "synonyms": ["neut#", "absolute neutrophils", "neutrophils absolute"],
    },
    "neutrophils": {
        "display_name": "Neutrophils",
        "category": "cbc_diff",
        "synonyms": ["neut%", "neutrophils", "neutrophil", "neutrofile"],
    },
    "lymphocytes_absolute": {
        "display_name": "Lymphocytes Absolute",
        "category": "cbc_diff",
        "synonyms": ["lymph#", "absolute lymphocytes", "lymphocytes absolute"],
    },
    "lymphocytes": {
        "display_name": "Lymphocytes",
        "category": "cbc_diff",
        "synonyms": ["lymph%", "lymphocytes", "lymphocyte", "limfocite"],
    },
    "monocytes_absolute": {
        "display_name": "Monocytes Absolute",
        "category": "cbc_diff",
        "synonyms": ["mono#", "absolute monocytes", "monocytes absolute"],
    },
    "monocytes": {
        "display_name": "Monocytes",
        "category": "cbc_diff",
        "synonyms": ["mono%", "monocytes", "monocyte", "monocite"],
    },
    "eosinophils_absolute": {
        "display_name": "Eosinophils Absolute",
        "category": "cbc_diff",
        "synonyms": ["eo#", "absolute eosinophils", "eosinophils absolute"],
    },
    "eosinophils": {
        "display_name": "Eosinophils",
        "category": "cbc_diff",
        "synonyms": ["eo%", "eosinophils", "eosinophil", "eozinofile"],
    },
    "basophils_absolute": {
        "display_name": "Basophils Absolute",
        "category": "cbc_diff",
        "synonyms": ["baso#", "absolute basophils", "basophils absolute"],
    },
    "basophils": {
        "display_name": "Basophils",
        "category": "cbc_diff",
        "synonyms": ["baso%", "basophils", "basophil", "bazofile"],
    },
    "immature_granulocytes_absolute": {
        "display_name": "Immature Granulocytes Absolute",
        "category": "cbc_diff",
        "synonyms": ["ig#", "absolute immature granulocytes"],
    },
    "immature_granulocytes": {
        "display_name": "Immature Granulocytes",
        "category": "cbc_diff",
        "synonyms": ["ig%", "immature granulocytes", "granulocite imature"],
    },
    "reticulocytes": {
        "display_name": "Reticulocytes",
        "category": "cbc_reticulocytes",
        "synonyms": ["ret%", "reticulocytes", "reticulocyte", "reticulocite"],
    },
    "reticulocytes_absolute": {
        "display_name": "Reticulocytes Absolute",
        "category": "cbc_reticulocytes",
        "synonyms": ["ret#", "absolute reticulocytes", "reticulocytes absolute"],
    },
    "irf": {
        "display_name": "IRF",
        "category": "cbc_reticulocytes",
        "synonyms": ["irf"],
    },
    "lfr": {
        "display_name": "LFR",
        "category": "cbc_reticulocytes",
        "synonyms": ["lfr"],
    },
    "mfr": {
        "display_name": "MFR",
        "category": "cbc_reticulocytes",
        "synonyms": ["mfr"],
    },
    "hfr": {
        "display_name": "HFR",
        "category": "cbc_reticulocytes",
        "synonyms": ["hfr"],
    },
    "ret_he": {
        "display_name": "RET-HE",
        "category": "cbc_reticulocytes",
        "synonyms": ["ret-he"],
    },
    "glucose": {
        "display_name": "Glucose",
        "category": "chemistry",
        "synonyms": ["glucose", "glycemia", "glicemie", "glucoza", "glucoză"],
    },
    "creatinine": {
        "display_name": "Creatinine",
        "category": "chemistry",
        "synonyms": ["creatinine", "creatinina", "creatinină"],
    },
    "urea": {
        "display_name": "Urea",
        "category": "chemistry",
        "synonyms": ["urea", "uree"],
    },
    "sodium": {
        "display_name": "Sodium",
        "category": "electrolytes",
        "synonyms": ["sodium", "na", "natriu", "sodiu"],
    },
    "potassium": {
        "display_name": "Potassium",
        "category": "electrolytes",
        "synonyms": ["potassium", "k", "kalium", "potasiu"],
    },
    "chloride": {
        "display_name": "Chloride",
        "category": "electrolytes",
        "synonyms": ["chloride", "cl", "clor", "cloruri"],
    },
    "ast": {
        "display_name": "AST",
        "category": "liver",
        "synonyms": ["ast", "asat", "tgo"],
    },
    "alt": {
        "display_name": "ALT",
        "category": "liver",
        "synonyms": ["alt", "alat", "tgp"],
    },
    "bilirubin_total": {
        "display_name": "Total Bilirubin",
        "category": "liver",
        "synonyms": ["total bilirubin", "bilirubin total", "bilirubina totala", "bilirubină totală"],
    },
    "cholesterol_total": {
        "display_name": "Total Cholesterol",
        "category": "lipids",
        "synonyms": ["total cholesterol", "cholesterol total", "colesterol total"],
    },
    "hdl": {
        "display_name": "HDL Cholesterol",
        "category": "lipids",
        "synonyms": ["hdl", "hdl cholesterol", "colesterol hdl"],
    },
    "ldl": {
        "display_name": "LDL Cholesterol",
        "category": "lipids",
        "synonyms": ["ldl", "ldl cholesterol", "colesterol ldl"],
    },
    "triglycerides": {
        "display_name": "Triglycerides",
        "category": "lipids",
        "synonyms": ["triglycerides", "trigliceride"],
    },
    "tsh": {
        "display_name": "TSH",
        "category": "thyroid",
        "synonyms": ["tsh"],
    },
    "ft4": {
        "display_name": "Free T4",
        "category": "thyroid",
        "synonyms": ["ft4", "free t4", "tiroxina libera", "tiroxină liberă"],
    },
}


def clean_test_name(name: str) -> str:
    value = str(name or "").strip().lower()
    value = re.sub(r".*?", "", value)
    value = re.sub(r"[^a-z0-9ăâîșşțţ\s\-\/#%]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_test_name(raw_name: str) -> dict:
    cleaned = clean_test_name(raw_name)

    for canonical_name, config in LAB_SYNONYMS.items():
        for synonym in config["synonyms"]:
            if cleaned == clean_test_name(synonym):
                return {
                    "canonical_name": canonical_name,
                    "display_name": config["display_name"],
                    "category": config["category"],
                    "raw_test_name": raw_name,
                }

    return {
        "canonical_name": None,
        "display_name": str(raw_name or "").strip(),
        "category": None,
        "raw_test_name": raw_name,
    }