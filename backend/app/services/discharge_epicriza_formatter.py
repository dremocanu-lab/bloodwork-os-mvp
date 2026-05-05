from __future__ import annotations

import re
import unicodedata
from typing import Any


NOISE_PATTERNS = [
    r"^\s*\d+\s*/\s*\d+\s*$",
    r"^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\s*$",
    r"192\.168\.[^\s]+",
    r"fundeni/gen_printabile/biletexternare",
    r"hipocrate\s*-\s*imprimare\s*fisa",
    r"^\s*epicriz[ăa]\s*$",
]

VISIT_START_RE = re.compile(
    r"^(la\s+(?:actuala|actualul|internarea)\b[^\n]*|revine\b[^\n]*|din\s+aprilie\s+\d{4}\b[^\n]*|aprilie\s+\d{4}\b[^\n]*)",
    re.IGNORECASE,
)

DATE_RE = re.compile(
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\.[IVXLCDM]+\s*\d{4}|\d{1,2}-\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{4}|\d{4})",
    re.IGNORECASE,
)

LAB_HINT_RE = re.compile(
    r"\b(hemograma|biochimie|coagulare|hb|ht|hg|leucocite|trombocite|fbg|inr|aptt|ldh|acid uric|ac uric|colesterol|cr|glc|alt|ast|rx|eco|ecografie|consult)\b",
    re.IGNORECASE,
)

TREATMENT_HINT_RE = re.compile(
    r"\b(tratament|hydrea|hydree|flebotomie|flebotomii|ifn|aspenter|mydocalm|movalis|alanerv|continua|s-a facut|s-au efectuat)\b",
    re.IGNORECASE,
)

FINDING_HINT_RE = re.compile(
    r"\b(stare|afebril|echilibrat|eritroza|tegument|ficat|splina|adenopatii|tranzit|mictiuni|acuza|ta\s*=|av\s*=|ots)\b",
    re.IGNORECASE,
)


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufeff", "")
    text = text.replace("\u00a0", " ")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("Â", "")
    text = text.replace("â€", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_noise_line(line: str) -> bool:
    cleaned = _clean_text(line)
    if not cleaned:
        return True

    lowered = cleaned.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in NOISE_PATTERNS)


def _should_join(previous: str, current: str) -> bool:
    if not previous or not current:
        return False

    previous = previous.strip()
    current = current.strip()

    if VISIT_START_RE.match(current):
        return False

    if re.match(r"^(hemograma|biochimie|coagulare|rx\s|eco\s|consult\s|tratament\s*:)", current, flags=re.IGNORECASE):
        return False

    if previous.endswith((".", ";", ":")):
        return False

    if current.startswith(("-", "•")):
        return False

    if len(previous) < 140 and not previous.endswith(","):
        return False

    return True


def normalize_epicriza_whitespace(text: str) -> str:
    raw_lines = [_clean_text(line) for line in _clean_text(text).splitlines()]
    lines = [line for line in raw_lines if not _is_noise_line(line)]

    normalized_lines: list[str] = []

    for line in lines:
        line = re.sub(r"\s+([,.;:])", r"\1", line)
        line = re.sub(r"([,.;:])(?=\S)", r"\1 ", line)
        line = re.sub(r"\s*/\s*", "/", line)
        line = re.sub(r"\s*=\s*", "=", line)
        line = re.sub(r"\s*->\s*", "->", line)
        line = re.sub(r"\bHg\b", "Hb", line)
        line = _clean_text(line)

        if normalized_lines and _should_join(normalized_lines[-1], line):
            normalized_lines[-1] = _clean_text(normalized_lines[-1].rstrip("-") + " " + line)
        else:
            normalized_lines.append(line)

    text = "\n".join(normalized_lines)

    text = re.sub(
        r"\n(?=(?:La\s+(?:actuala|actualul|internarea)|Revine)\b)",
        "\n\n",
        text,
        flags=re.IGNORECASE,
    )

    return text.strip()


def _extract_date(text: str) -> str | None:
    match = DATE_RE.search(text)
    return match.group(1).strip() if match else None


def _event_title(first_line: str) -> str:
    first_line = _clean_text(first_line)
    if len(first_line) <= 100:
        return first_line
    return first_line[:97].rstrip() + "..."


def _classify_event_lines(lines: list[str]) -> dict[str, str]:
    buckets = {
        "findings": [],
        "labs": [],
        "imaging_consults": [],
        "treatment": [],
        "other": [],
    }

    for line in lines:
        clean = _clean_text(line)
        if not clean:
            continue

        if TREATMENT_HINT_RE.search(clean):
            buckets["treatment"].append(clean)
        elif re.search(r"\b(rx|eco|ecografie|consult|fevs|neurologic|cardiologic)\b", clean, flags=re.IGNORECASE):
            buckets["imaging_consults"].append(clean)
        elif LAB_HINT_RE.search(clean):
            buckets["labs"].append(clean)
        elif FINDING_HINT_RE.search(clean):
            buckets["findings"].append(clean)
        else:
            buckets["other"].append(clean)

    return {key: "\n".join(value).strip() for key, value in buckets.items() if value}


def _split_timeline_events(clean_text: str) -> tuple[str, list[dict[str, Any]]]:
    lines = [line for line in clean_text.splitlines() if line.strip()]

    baseline_lines: list[str] = []
    events: list[dict[str, Any]] = []
    current_event_lines: list[str] = []

    def flush_event() -> None:
        nonlocal current_event_lines

        if not current_event_lines:
            return

        first_line = current_event_lines[0]
        body_lines = current_event_lines[1:]

        events.append(
            {
                "date": _extract_date(first_line),
                "title": _event_title(first_line),
                "intro": first_line,
                "sections": _classify_event_lines(body_lines),
                "raw_text": "\n".join(current_event_lines).strip(),
            }
        )

        current_event_lines = []

    for line in lines:
        if VISIT_START_RE.match(line):
            flush_event()
            current_event_lines = [line]
        elif current_event_lines:
            current_event_lines.append(line)
        else:
            baseline_lines.append(line)

    flush_event()
    return "\n".join(baseline_lines).strip(), events


def _extract_baseline_parts(baseline_text: str) -> dict[str, str]:
    lines = [line for line in baseline_text.splitlines() if line.strip()]

    parts = {
        "diagnosis_baseline": [],
        "prior_treatment": [],
        "pathology_genetics": [],
        "other": [],
    }

    for line in lines:
        clean = _clean_text(line)
        lower = clean.lower()

        if lower.startswith("la diagnostic") or re.search(r"\b(hb|ht|epo|sato2|splina|eritroza|fal|colonii eritroide)\b", lower):
            parts["diagnosis_baseline"].append(clean)
        elif re.search(r"\b(tratament|ifn|flebotomii|hydrea|hydree)\b", lower):
            parts["prior_treatment"].append(clean)
        elif re.search(r"\b(pbmo|jak|smpc|pv|biopsie|megacariocite|eritroblasti)\b", lower):
            parts["pathology_genetics"].append(clean)
        else:
            parts["other"].append(clean)

    return {key: "\n".join(value).strip() for key, value in parts.items() if value}


def format_epicriza_section(text: str) -> dict[str, Any]:
    clean_text = normalize_epicriza_whitespace(text)
    baseline_text, timeline_events = _split_timeline_events(clean_text)
    baseline_parts = _extract_baseline_parts(baseline_text)

    return {
        "mode": "deterministic_epicriza_formatter",
        "clean_text": clean_text,
        "baseline": baseline_parts,
        "timeline_events": timeline_events,
        "event_count": len(timeline_events),
    }