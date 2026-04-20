import re


LAB_SYNONYMS = {
    "hemoglobin": {
        "display_name": "Hemoglobin",
        "category": "cbc",
        "synonyms": [
            "hemoglobin", "haemoglobin", "hb", "hgb",
            "hemoglobina", "hemoglobină"
        ],
    },
    "wbc": {
        "display_name": "White Blood Cell Count",
        "category": "cbc",
        "synonyms": [
            "wbc", "white blood cell count", "white cell count",
            "total leucocyte count", "total leukocyte count", "tlc",
            "leucocite", "leukocite", "numar leucocite", "număr leucocite"
        ],
    },
    "rbc": {
        "display_name": "Red Blood Cell Count",
        "category": "cbc",
        "synonyms": [
            "rbc", "rbc count", "red blood cell count", "total rbc count",
            "eritrocite", "numar eritrocite", "număr eritrocite"
        ],
    },
    "platelet_count": {
        "display_name": "Platelet Count",
        "category": "cbc",
        "synonyms": [
            "platelet count", "platelets", "platelet", "plt",
            "trombocite", "numar trombocite", "număr trombocite"
        ],
    },
    "hematocrit": {
        "display_name": "Hematocrit",
        "category": "cbc",
        "synonyms": [
            "hematocrit", "haematocrit", "hct", "ht",
            "pcv", "packed cell volume",
            "hematocrit", "hematocritul"
        ],
    },
    "mcv": {
        "display_name": "MCV",
        "category": "cbc",
        "synonyms": [
            "mcv", "mean corpuscular volume",
            "vem", "volum eritrocitar mediu"
        ],
    },
    "mch": {
        "display_name": "MCH",
        "category": "cbc",
        "synonyms": [
            "mch", "hemoglobina eritrocitara medie", "hemoglobină eritrocitară medie"
        ],
    },
    "mchc": {
        "display_name": "MCHC",
        "category": "cbc",
        "synonyms": [
            "mchc",
            "concentratia medie a hemoglobinei eritrocitare",
            "concentrația medie a hemoglobinei eritrocitare"
        ],
    },
    "rdw": {
        "display_name": "RDW",
        "category": "cbc",
        "synonyms": [
            "rdw", "rdw-cv", "rdw cv", "rdw-sd", "rdw sd",
            "largimea distributiei eritrocitare",
            "lărgimea distribuției eritrocitare"
        ],
    },
    "neutrophils": {
        "display_name": "Neutrophils",
        "category": "cbc_diff",
        "synonyms": ["neutrophils", "neutrophil", "neutrofile"],
    },
    "lymphocytes": {
        "display_name": "Lymphocytes",
        "category": "cbc_diff",
        "synonyms": ["lymphocytes", "lymphocyte", "limfocite"],
    },
    "monocytes": {
        "display_name": "Monocytes",
        "category": "cbc_diff",
        "synonyms": ["monocytes", "monocyte", "monocite"],
    },
    "eosinophils": {
        "display_name": "Eosinophils",
        "category": "cbc_diff",
        "synonyms": ["eosinophils", "eosinophil", "eozinofile"],
    },
    "basophils": {
        "display_name": "Basophils",
        "category": "cbc_diff",
        "synonyms": ["basophils", "basophil", "bazofile"],
    },
    "mpv": {
        "display_name": "MPV",
        "category": "cbc_platelets",
        "synonyms": ["mpv", "mean platelet volume", "volum trombocitar mediu"],
    },
    "pdw": {
        "display_name": "PDW",
        "category": "cbc_platelets",
        "synonyms": ["pdw", "platelet distribution width", "latimea distributiei trombocitare"],
    },
    "pct": {
        "display_name": "PCT",
        "category": "cbc_platelets",
        "synonyms": ["pct", "plateletcrit", "trombocrit"],
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
        "synonyms": [
            "total bilirubin", "bilirubin total", "bilirubina totala", "bilirubină totală"
        ],
    },
    "cholesterol_total": {
        "display_name": "Total Cholesterol",
        "category": "lipids",
        "synonyms": [
            "total cholesterol", "cholesterol total", "colesterol total"
        ],
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
    value = name.strip().lower()
    value = re.sub(r"\(.*?\)", "", value)
    value = re.sub(r"[^a-z0-9ăâîșşțţ\s\-\/]", " ", value)
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
        "display_name": raw_name.strip(),
        "category": None,
        "raw_test_name": raw_name,
    }