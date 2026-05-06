export function cleanOneLine(value?: string | null) {
  return String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function formatSectionPreview(value?: string | null, limit = 86) {
  const text = cleanOneLine(value);

  if (!text) return "No extracted text.";
  if (text.length <= limit) return text;

  return `${text.slice(0, limit)}...`;
}

function cleanDisplayLine(value: string) {
  return value
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+/g, " ")
    .trim();
}

function normalizeForTextRules(value: string) {
  return cleanDisplayLine(value)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function isHardSectionBreak(line: string) {
  const normalized = normalizeForTextRules(line);

  return (
    normalized === "---" ||
    /^[-_=]{3,}$/.test(normalized) ||
    /^\[[^\]]+\]$/.test(line.trim()) ||
    [
      "epicriza",
      "diagnostic",
      "diagnostice",
      "investigatii",
      "investigatii / rezultate",
      "tratament",
      "tratament recomandat",
      "recomandari",
      "recomandari / follow-up",
      "stare la externare",
    ].some((heading) => normalized === heading || normalized.startsWith(`${heading}:`))
  );
}

function startsNewClinicalEvent(line: string) {
  const normalized = normalizeForTextRules(line);

  return Boolean(
    /^(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b/.test(normalized) ||
      /^(la actual|la internarea|revine|se revine|control|reevaluare|la reevaluare)\b/.test(normalized) ||
      /^(hemograma|biochimie|coagulare|rx cp|ecografie|eco abd|eco|ct|rmn|irm|ecg|ekg)\s*:/.test(normalized) ||
      /^(consult cardiologic|consult neurologic|consult|tratament|flebotomie|s-a efectuat|s-au efectuat|continua tratamentul|acuza)\b/.test(normalized) ||
      /^(pbmo|jak homozigot|sat ?o2|beta2 microglobulina)\b/.test(normalized)
  );
}

function isMeasurementListLine(line: string) {
  const normalized = normalizeForTextRules(line);

  return Boolean(
    /^[-•]/.test(line.trim()) ||
      /^(hb|ht|l:|ldh|ac uric|splina|fal|epo|ta=|av=)\b/.test(normalized) ||
      /^[a-z]{1,4}\s*[:=]\s*\d/.test(normalized)
  );
}

function isObviousContinuationLine(line: string) {
  const normalized = normalizeForTextRules(line);

  return Boolean(
    /^(usoare|usoara|modificari|degenerative|normal|normale|fara|cu|in|si|sau|tip|prezent|prezenta|palpabile|dilatatii|diam|rg\.?|stg\.?|sapt\.?|cp\/zi|mmhg|b\/min|mmc)\b/.test(
      normalized
    )
  );
}

function previousLooksIncomplete(line: string) {
  const normalized = normalizeForTextRules(line);

  return Boolean(
    /[,;:/(-]$/.test(normalized) ||
      /\b(cu|fara|si|sau|la|in|de|pentru|prin|tip|diam|hd|rg|stg|normal|normale)\.?$/.test(normalized)
  );
}

function shouldJoin(previousLine: string, currentLine: string) {
  const previous = cleanDisplayLine(previousLine);
  const current = cleanDisplayLine(currentLine);

  if (!previous || !current) return false;
  if (isHardSectionBreak(previous) || isHardSectionBreak(current)) return false;

  if (previous.endsWith("-")) return true;

  if (isObviousContinuationLine(current)) return true;

  if (previousLooksIncomplete(previous)) return true;

  if (previous.length > 70 && !startsNewClinicalEvent(current) && !isMeasurementListLine(current)) {
    return true;
  }

  if (!startsNewClinicalEvent(current) && !isMeasurementListLine(current)) {
    const currentStartsLower = /^[a-zăâîșț]/.test(current);
    if (currentStartsLower) return true;
  }

  return false;
}

function joinLines(previousLine: string, currentLine: string) {
  const previous = previousLine.trimEnd();
  const current = currentLine.trimStart();

  if (!previous) return current;
  if (!current) return previous;

  if (previous.endsWith("-")) {
    return `${previous}${current}`;
  }

  return `${previous} ${current}`;
}

export function formatPdfLikeText(value?: string | null) {
  const rawLines = String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+/g, " ")
    .split("\n");

  const cleanedLines = rawLines.map(cleanDisplayLine);

  const outputLines: string[] = [];

  for (let index = 0; index < cleanedLines.length; index += 1) {
    const line = cleanedLines[index];

    if (!line) {
      const nextLine = cleanedLines[index + 1] || "";
      const previousLine = outputLines[outputLines.length - 1] || "";

      // OCR sometimes inserts a fake blank line inside a sentence.
      // If the next line is clearly a continuation, skip this blank line.
      if (previousLine && nextLine && shouldJoin(previousLine, nextLine)) {
        continue;
      }

      if (outputLines.length && outputLines[outputLines.length - 1] !== "") {
        outputLines.push("");
      }

      continue;
    }

    if (!outputLines.length) {
      outputLines.push(line);
      continue;
    }

    const previous = outputLines[outputLines.length - 1];

    if (shouldJoin(previous, line)) {
      outputLines[outputLines.length - 1] = joinLines(previous, line);
    } else {
      outputLines.push(line);
    }
  }

  return outputLines
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}