import re
import unicodedata


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    value = value.lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("µ", "u")
    value = value.replace("×", "x")
    value = re.sub(r"[^a-z0-9%+#./\- ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


CBC_TEST_DEFINITIONS = [
    {
        "canonical_name": "wbc",
        "display_name": "White Blood Cell Count",
        "short_name": "WBC",
        "category": "cbc_core",
        "synonyms": [
            "wbc",
            "white blood cell count",
            "white blood cells",
            "white cells",
            "leukocytes",
            "leucocytes",
            "total leukocyte count",
            "total leucocyte count",
            "tlc",
            "leucocite",
            "leukocite",
            "numar leucocite",
            "număr leucocite",
        ],
    },
    {
        "canonical_name": "rbc",
        "display_name": "Red Blood Cell Count",
        "short_name": "RBC",
        "category": "cbc_core",
        "synonyms": [
            "rbc",
            "red blood cell count",
            "red blood cells",
            "erythrocytes",
            "eritrocite",
            "total rbc count",
            "numar eritrocite",
            "număr eritrocite",
        ],
    },
    {
        "canonical_name": "hemoglobin",
        "display_name": "Hemoglobin",
        "short_name": "HGB",
        "category": "cbc_core",
        "synonyms": [
            "hemoglobin",
            "haemoglobin",
            "hgb",
            "hb",
            "hemoglobina",
            "hemoglobină",
        ],
    },
    {
        "canonical_name": "hematocrit",
        "display_name": "Hematocrit",
        "short_name": "HCT",
        "category": "cbc_core",
        "synonyms": [
            "hematocrit",
            "haematocrit",
            "hct",
            "ht",
            "pcv",
            "packed cell volume",
            "hematocritul",
        ],
    },
    {
        "canonical_name": "mcv",
        "display_name": "Mean Corpuscular Volume",
        "short_name": "MCV",
        "category": "cbc_indices",
        "synonyms": [
            "mcv",
            "mean corpuscular volume",
            "mean cell volume",
            "vem",
            "volum eritrocitar mediu",
        ],
    },
    {
        "canonical_name": "mch",
        "display_name": "Mean Corpuscular Hemoglobin",
        "short_name": "MCH",
        "category": "cbc_indices",
        "synonyms": [
            "mch",
            "mean corpuscular hemoglobin",
            "mean cell hemoglobin",
            "hemoglobina eritrocitara medie",
            "hemoglobină eritrocitară medie",
            "hemoglobina eritrocitara med",
        ],
    },
    {
        "canonical_name": "mchc",
        "display_name": "Mean Corpuscular Hemoglobin Concentration",
        "short_name": "MCHC",
        "category": "cbc_indices",
        "synonyms": [
            "mchc",
            "mean corpuscular hemoglobin concentration",
            "concentratia medie a hemoglobinei eritrocitare",
            "concentrația medie a hemoglobinei eritrocitare",
        ],
    },
    {
        "canonical_name": "rdw_cv",
        "display_name": "Red Cell Distribution Width - CV",
        "short_name": "RDW-CV",
        "category": "cbc_indices",
        "synonyms": [
            "rdw-cv",
            "rdw cv",
            "rdw_cv",
            "red cell distribution width cv",
            "largimea distributiei eritrocitare cv",
            "lărgimea distribuției eritrocitare cv",
        ],
    },
    {
        "canonical_name": "rdw_sd",
        "display_name": "Red Cell Distribution Width - SD",
        "short_name": "RDW-SD",
        "category": "cbc_indices",
        "synonyms": [
            "rdw-sd",
            "rdw sd",
            "rdw_sd",
            "red cell distribution width sd",
            "largimea distributiei eritrocitare sd",
            "lărgimea distribuției eritrocitare sd",
        ],
    },
    {
        "canonical_name": "rdw",
        "display_name": "Red Cell Distribution Width",
        "short_name": "RDW",
        "category": "cbc_indices",
        "synonyms": [
            "rdw",
            "red cell distribution width",
            "largimea distributiei eritrocitare",
            "lărgimea distribuției eritrocitare",
        ],
    },
    {
        "canonical_name": "platelet_count",
        "display_name": "Platelet Count",
        "short_name": "PLT",
        "category": "cbc_platelets",
        "synonyms": [
            "plt",
            "platelet count",
            "platelets",
            "platelet",
            "thrombocytes",
            "trombocite",
            "numar trombocite",
            "număr trombocite",
        ],
    },
    {
        "canonical_name": "mpv",
        "display_name": "Mean Platelet Volume",
        "short_name": "MPV",
        "category": "cbc_platelets",
        "synonyms": [
            "mpv",
            "mean platelet volume",
            "volum trombocitar mediu",
        ],
    },
    {
        "canonical_name": "pdw",
        "display_name": "Platelet Distribution Width",
        "short_name": "PDW",
        "category": "cbc_platelets",
        "synonyms": [
            "pdw",
            "platelet distribution width",
            "latimea distributiei trombocitare",
            "lățimea distribuției trombocitare",
        ],
    },
    {
        "canonical_name": "pct",
        "display_name": "Plateletcrit",
        "short_name": "PCT",
        "category": "cbc_platelets",
        "synonyms": [
            "pct",
            "plateletcrit",
            "platelet crit",
            "trombocrit",
        ],
    },
    {
        "canonical_name": "neutrophils_percent",
        "display_name": "Neutrophils %",
        "short_name": "NEUT %",
        "category": "cbc_differential",
        "synonyms": [
            "neutrophils %",
            "neutrophil %",
            "neut %",
            "neut%",
            "ne%",
            "neutrofile %",
            "neutrofile%",
        ],
    },
    {
        "canonical_name": "neutrophils_absolute",
        "display_name": "Neutrophils Absolute",
        "short_name": "NEUT #",
        "category": "cbc_differential",
        "synonyms": [
            "neutrophils #",
            "neutrophil #",
            "neut abs",
            "neut absolute",
            "absolute neutrophils",
            "neut#",
            "neutrofile #",
            "neutrofile abs",
            "numar absolut neutrofile",
            "număr absolut neutrofile",
        ],
    },
    {
        "canonical_name": "lymphocytes_percent",
        "display_name": "Lymphocytes %",
        "short_name": "LYMPH %",
        "category": "cbc_differential",
        "synonyms": [
            "lymphocytes %",
            "lymphocyte %",
            "lymph %",
            "lymph%",
            "ly%",
            "limfocite %",
            "limfocite%",
        ],
    },
    {
        "canonical_name": "lymphocytes_absolute",
        "display_name": "Lymphocytes Absolute",
        "short_name": "LYMPH #",
        "category": "cbc_differential",
        "synonyms": [
            "lymphocytes #",
            "lymphocyte #",
            "lymph abs",
            "lymph absolute",
            "absolute lymphocytes",
            "lymph#",
            "limfocite #",
            "limfocite abs",
            "numar absolut limfocite",
            "număr absolut limfocite",
        ],
    },
    {
        "canonical_name": "monocytes_percent",
        "display_name": "Monocytes %",
        "short_name": "MONO %",
        "category": "cbc_differential",
        "synonyms": [
            "monocytes %",
            "monocyte %",
            "mono %",
            "mono%",
            "mo%",
            "monocite %",
            "monocite%",
        ],
    },
    {
        "canonical_name": "monocytes_absolute",
        "display_name": "Monocytes Absolute",
        "short_name": "MONO #",
        "category": "cbc_differential",
        "synonyms": [
            "monocytes #",
            "monocyte #",
            "mono abs",
            "mono absolute",
            "absolute monocytes",
            "mono#",
            "monocite #",
            "monocite abs",
            "numar absolut monocite",
            "număr absolut monocite",
        ],
    },
    {
        "canonical_name": "eosinophils_percent",
        "display_name": "Eosinophils %",
        "short_name": "EOS %",
        "category": "cbc_differential",
        "synonyms": [
            "eosinophils %",
            "eosinophil %",
            "eos %",
            "eos%",
            "eo%",
            "eozinofile %",
            "eozinofile%",
        ],
    },
    {
        "canonical_name": "eosinophils_absolute",
        "display_name": "Eosinophils Absolute",
        "short_name": "EOS #",
        "category": "cbc_differential",
        "synonyms": [
            "eosinophils #",
            "eosinophil #",
            "eos abs",
            "eos absolute",
            "absolute eosinophils",
            "eos#",
            "eozinofile #",
            "eozinofile abs",
            "numar absolut eozinofile",
            "număr absolut eozinofile",
        ],
    },
    {
        "canonical_name": "basophils_percent",
        "display_name": "Basophils %",
        "short_name": "BASO %",
        "category": "cbc_differential",
        "synonyms": [
            "basophils %",
            "basophil %",
            "baso %",
            "baso%",
            "ba%",
            "bazofile %",
            "bazofile%",
        ],
    },
    {
        "canonical_name": "basophils_absolute",
        "display_name": "Basophils Absolute",
        "short_name": "BASO #",
        "category": "cbc_differential",
        "synonyms": [
            "basophils #",
            "basophil #",
            "baso abs",
            "baso absolute",
            "absolute basophils",
            "baso#",
            "bazofile #",
            "bazofile abs",
            "numar absolut bazofile",
            "număr absolut bazofile",
        ],
    },
    {
        "canonical_name": "immature_granulocytes_percent",
        "display_name": "Immature Granulocytes %",
        "short_name": "IG %",
        "category": "cbc_differential",
        "synonyms": [
            "immature granulocytes %",
            "ig %",
            "ig%",
            "granulocite imature %",
            "granulocite imature%",
        ],
    },
    {
        "canonical_name": "immature_granulocytes_absolute",
        "display_name": "Immature Granulocytes Absolute",
        "short_name": "IG #",
        "category": "cbc_differential",
        "synonyms": [
            "immature granulocytes #",
            "ig #",
            "ig abs",
            "ig absolute",
            "granulocite imature #",
            "granulocite imature abs",
        ],
    },
    {
        "canonical_name": "nrbc_percent",
        "display_name": "Nucleated Red Blood Cells %",
        "short_name": "NRBC %",
        "category": "cbc_differential",
        "synonyms": [
            "nrbc %",
            "nrbc%",
            "nucleated red blood cells %",
            "eritroblasti %",
            "eritroblaști %",
        ],
    },
    {
        "canonical_name": "nrbc_absolute",
        "display_name": "Nucleated Red Blood Cells Absolute",
        "short_name": "NRBC #",
        "category": "cbc_differential",
        "synonyms": [
            "nrbc #",
            "nrbc abs",
            "nrbc absolute",
            "nucleated red blood cells #",
            "eritroblasti #",
            "eritroblaști #",
        ],
    },
]


EXTRA_LAB_DEFINITIONS = [
    {
        "canonical_name": "glucose",
        "display_name": "Glucose",
        "short_name": "Glucose",
        "category": "chemistry",
        "synonyms": ["glucose", "glycemia", "glicemie", "glucoza", "glucoză"],
    },
    {
        "canonical_name": "creatinine",
        "display_name": "Creatinine",
        "short_name": "Creatinine",
        "category": "chemistry",
        "synonyms": ["creatinine", "creatinina", "creatinină"],
    },
    {
        "canonical_name": "urea",
        "display_name": "Urea",
        "short_name": "Urea",
        "category": "chemistry",
        "synonyms": ["urea", "uree"],
    },
    {
        "canonical_name": "sodium",
        "display_name": "Sodium",
        "short_name": "Na",
        "category": "electrolytes",
        "synonyms": ["sodium", "na", "natriu", "sodiu"],
    },
    {
        "canonical_name": "potassium",
        "display_name": "Potassium",
        "short_name": "K",
        "category": "electrolytes",
        "synonyms": ["potassium", "k", "kalium", "potasiu"],
    },
    {
        "canonical_name": "chloride",
        "display_name": "Chloride",
        "short_name": "Cl",
        "category": "electrolytes",
        "synonyms": ["chloride", "cl", "clor", "cloruri"],
    },
    {
        "canonical_name": "ast",
        "display_name": "AST",
        "short_name": "AST",
        "category": "liver",
        "synonyms": ["ast", "asat", "tgo"],
    },
    {
        "canonical_name": "alt",
        "display_name": "ALT",
        "short_name": "ALT",
        "category": "liver",
        "synonyms": ["alt", "alat", "tgp"],
    },
    {
        "canonical_name": "bilirubin_total",
        "display_name": "Total Bilirubin",
        "short_name": "Total Bilirubin",
        "category": "liver",
        "synonyms": ["total bilirubin", "bilirubin total", "bilirubina totala", "bilirubină totală"],
    },
    {
        "canonical_name": "cholesterol_total",
        "display_name": "Total Cholesterol",
        "short_name": "Total Cholesterol",
        "category": "lipids",
        "synonyms": ["total cholesterol", "cholesterol total", "colesterol total"],
    },
    {
        "canonical_name": "hdl",
        "display_name": "HDL Cholesterol",
        "short_name": "HDL",
        "category": "lipids",
        "synonyms": ["hdl", "hdl cholesterol", "colesterol hdl"],
    },
    {
        "canonical_name": "ldl",
        "display_name": "LDL Cholesterol",
        "short_name": "LDL",
        "category": "lipids",
        "synonyms": ["ldl", "ldl cholesterol", "colesterol ldl"],
    },
    {
        "canonical_name": "triglycerides",
        "display_name": "Triglycerides",
        "short_name": "Triglycerides",
        "category": "lipids",
        "synonyms": ["triglycerides", "trigliceride"],
    },
    {
        "canonical_name": "tsh",
        "display_name": "TSH",
        "short_name": "TSH",
        "category": "thyroid",
        "synonyms": ["tsh", "thyroid stimulating hormone", "hormon tireostimulant"],
    },
    {
        "canonical_name": "free_t4",
        "display_name": "Free T4",
        "short_name": "Free T4",
        "category": "thyroid",
        "synonyms": ["free t4", "ft4", "tiroxina libera", "tiroxină liberă"],
    },
]


LAB_DEFINITIONS = CBC_TEST_DEFINITIONS + EXTRA_LAB_DEFINITIONS

LAB_SYNONYMS = {
    definition["canonical_name"]: {
        "display_name": definition["display_name"],
        "short_name": definition.get("short_name", definition["display_name"]),
        "category": definition["category"],
        "synonyms": definition["synonyms"],
    }
    for definition in LAB_DEFINITIONS
}


def get_cbc_template() -> list[dict]:
    return [
        {
            "raw_test_name": definition["short_name"],
            "canonical_name": definition["canonical_name"],
            "display_name": definition["display_name"],
            "short_name": definition["short_name"],
            "category": definition["category"],
            "value": None,
            "flag": None,
            "reference_range": None,
            "unit": None,
            "source": "template",
            "is_present": False,
        }
        for definition in CBC_TEST_DEFINITIONS
    ]


def get_definition_by_canonical(canonical_name: str) -> dict | None:
    for definition in LAB_DEFINITIONS:
        if definition["canonical_name"] == canonical_name:
            return definition
    return None


def synonym_matches_line(line: str, synonym: str) -> bool:
    normalized_line = normalize_text(line)
    normalized_synonym = normalize_text(synonym)

    if not normalized_line or not normalized_synonym:
        return False

    escaped = re.escape(normalized_synonym).replace("\\ ", r"\s+")
    pattern = rf"(^|[^a-z0-9]){escaped}([^a-z0-9]|$)"
    return re.search(pattern, normalized_line) is not None


def identify_test_from_line(line: str) -> dict | None:
    normalized_line = normalize_text(line)

    if not normalized_line:
        return None

    ordered_definitions = sorted(
        LAB_DEFINITIONS,
        key=lambda item: max(len(syn) for syn in item["synonyms"]),
        reverse=True,
    )

    for definition in ordered_definitions:
        for synonym in definition["synonyms"]:
            if synonym_matches_line(normalized_line, synonym):
                return definition

    return None


def normalize_test_name(raw_test_name: str | None) -> dict:
    raw = raw_test_name or ""
    normalized_raw = normalize_text(raw)

    for definition in LAB_DEFINITIONS:
        for synonym in definition["synonyms"]:
            if normalize_text(synonym) == normalized_raw or synonym_matches_line(raw, synonym):
                return {
                    "raw_test_name": raw,
                    "canonical_name": definition["canonical_name"],
                    "display_name": definition["display_name"],
                    "short_name": definition.get("short_name", definition["display_name"]),
                    "category": definition["category"],
                }

    cleaned_display = raw.strip() or "Unknown Test"

    return {
        "raw_test_name": raw,
        "canonical_name": normalized_raw.replace(" ", "_") if normalized_raw else "unknown_test",
        "display_name": cleaned_display,
        "short_name": cleaned_display,
        "category": "other",
    }