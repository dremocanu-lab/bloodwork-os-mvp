"""
Lookup official drug information from RxNorm and DailyMed (NLM).
Uses only Python standard library — no extra dependencies required.
"""

import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Optional

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
DAILYMED_BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
TIMEOUT = 12

# LOINC codes for key drug label sections we want to extract
SECTION_CODES = {
    "34067-9": "Indications and Usage",
    "34068-7": "Dosage and Administration",
    "43685-7": "Warnings and Precautions",
    "34071-1": "Warnings",
    "34084-4": "Adverse Reactions",
    "34073-7": "Drug Interactions",
    "34070-3": "Contraindications",
    "42228-7": "Pregnancy",
}

# Terms too vague to match automatically
VAGUE_TERMS = {
    "pill", "tablet", "capsule", "injection", "medicine", "medication",
    "drug", "antibiotic", "painkiller", "pain pill", "pain killer",
    "blood pressure", "blood pressure pill", "stomach medicine", "stomach pill",
    "sleep pill", "sleeping pill", "antidepressant", "allergy", "allergy pill",
    "vitamin", "supplement", "steroid", "statin", "diuretic", "beta blocker",
}


def _fetch_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Bragi-Health/1.0"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:3000]


def _is_vague(name: str) -> bool:
    return name.strip().lower() in VAGUE_TERMS


def _search_rxnorm(name: str) -> dict:
    """
    Returns one of:
      {"status": "matched", "rxcui": str, "rx_name": str}
      {"status": "multiple", "candidates": [...]}
      {"status": "not_matched"}
      {"status": "vague"}
    """
    if _is_vague(name):
        return {"status": "vague"}

    encoded = urllib.parse.quote(name.strip())

    # 1. Exact search (search=0 = exact, search=2 = normalised)
    exact_data = _fetch_json(f"{RXNORM_BASE}/rxcui.json?name={encoded}&search=2")
    if exact_data:
        ids = exact_data.get("idGroup", {}).get("rxnormId") or []
        if ids:
            rxcui = ids[0]
            props = _fetch_json(f"{RXNORM_BASE}/rxcui/{rxcui}/properties.json")
            rx_name = (props or {}).get("properties", {}).get("name", name) if props else name
            return {"status": "matched", "rxcui": rxcui, "rx_name": rx_name}

    # 2. Approximate search
    approx_data = _fetch_json(f"{RXNORM_BASE}/approximateTerm.json?term={encoded}&maxEntries=5")
    if not approx_data:
        return {"status": "not_matched"}

    candidates = approx_data.get("approximateGroup", {}).get("candidate") or []
    strong = [c for c in candidates if int(c.get("score", "0")) >= 60]

    if not strong:
        return {"status": "not_matched"}

    unique_cuis = {c["rxcui"] for c in strong}

    if len(unique_cuis) == 1:
        c = strong[0]
        return {"status": "matched", "rxcui": c["rxcui"], "rx_name": c["name"]}

    # Multiple distinct concepts — return for user selection
    return {
        "status": "multiple",
        "candidates": [
            {"rxcui": c["rxcui"], "name": c["name"], "score": c.get("score")}
            for c in strong[:5]
        ],
    }


def _fetch_dailymed(rxcui: str) -> dict:
    """Fetch DailyMed SPL info for a given RxCUI. Returns {} on failure."""
    spls_data = _fetch_json(f"{DAILYMED_BASE}/spls.json?rxcui={rxcui}&pagesize=3")
    if not spls_data:
        return {}

    spls = spls_data.get("data") or []
    if not spls:
        return {}

    spl = spls[0]
    setid = spl.get("setid")
    if not setid:
        return {}

    title = spl.get("title", "")
    published = spl.get("published_date") or spl.get("effective_time", "")
    source_url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"

    sections_data = _fetch_json(f"{DAILYMED_BASE}/spls/{setid}/sections.json")
    extracted = {}
    if sections_data:
        for sec in (sections_data.get("data") or []):
            code = sec.get("code")
            if code in SECTION_CODES:
                text = _strip_html(sec.get("content") or "")
                if text:
                    extracted[SECTION_CODES[code]] = text

    return {
        "setid": setid,
        "title": title,
        "published_date": published,
        "source_url": source_url,
        "sections": extracted,
    }


def lookup_medication(name: str, rxcui_override: Optional[str] = None) -> dict:
    """
    Main entry point. Always returns a dict suitable for writing to
    PatientMedication official_* fields.

    Return shape:
    {
      "official_match_status": str,
      "rxnorm_rxcui": str | None,
      "official_source_name": str | None,
      "official_source_url": str | None,
      "dailymed_setid": str | None,
      "official_label_date": str | None,
      "official_info_json": str | None,
      "official_retrieved_at": str,
    }
    """
    now = datetime.now(UTC).isoformat()

    def _empty(status: str, info: Optional[dict] = None) -> dict:
        return {
            "official_match_status": status,
            "rxnorm_rxcui": None,
            "official_source_name": None,
            "official_source_url": None,
            "dailymed_setid": None,
            "official_label_date": None,
            "official_info_json": json.dumps(info) if info else None,
            "official_retrieved_at": now,
        }

    try:
        if rxcui_override:
            rx = {"status": "matched", "rxcui": rxcui_override, "rx_name": name}
        else:
            rx = _search_rxnorm(name)

        status = rx["status"]

        if status == "vague":
            return _empty("vague")
        if status == "not_matched":
            return _empty("not_matched")
        if status == "multiple":
            return _empty("multiple", {"candidates": rx["candidates"]})

        # Matched
        rxcui = rx["rxcui"]
        rx_name = rx["rx_name"]

        dm = _fetch_dailymed(rxcui)

        if not dm:
            info = {"rxnorm_name": rx_name, "rxcui": rxcui}
            return {
                "official_match_status": "matched",
                "rxnorm_rxcui": rxcui,
                "official_source_name": "RxNorm / NLM",
                "official_source_url": f"https://mor.nlm.nih.gov/RxNav/search?searchBy=RXCUI&searchTerm={rxcui}",
                "dailymed_setid": None,
                "official_label_date": None,
                "official_info_json": json.dumps(info),
                "official_retrieved_at": now,
            }

        info = {
            "rxnorm_name": rx_name,
            "rxcui": rxcui,
            "label_title": dm.get("title", ""),
            "sections": dm.get("sections", {}),
        }

        return {
            "official_match_status": "matched",
            "rxnorm_rxcui": rxcui,
            "official_source_name": "DailyMed / National Library of Medicine",
            "official_source_url": dm.get("source_url"),
            "dailymed_setid": dm.get("setid"),
            "official_label_date": dm.get("published_date"),
            "official_info_json": json.dumps(info),
            "official_retrieved_at": now,
        }

    except Exception:
        return {
            "official_match_status": "error",
            "rxnorm_rxcui": None,
            "official_source_name": None,
            "official_source_url": None,
            "dailymed_setid": None,
            "official_label_date": None,
            "official_info_json": None,
            "official_retrieved_at": now,
        }
