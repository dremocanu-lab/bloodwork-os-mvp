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

function isSeparatorLine(line: string) {
  const normalized = normalizeForTextRules(line);

  return (
    normalized === "---" ||
    /^[-_=]{3,}$/.test(normalized) ||
    /^\[[^\]]+\]$/.test(line.trim())
  );
}

function isMajorSectionHeading(line: string) {
  const normalized = normalizeForTextRules(line);

  return [
    "epicriza",
    "evolutie si tratament",
    "diagnostic",
    "diagnostice",
    "investigatii",
    "investigatii / rezultate",
    "tratament",
    "tratament recomandat",
    "recomandari",
    "recomandari / follow-up",
    "stare la externare",
  ].some((heading) => normalized === heading || normalized.startsWith(`${heading}:`));
}

function startsNewClinicalThought(line: string) {
  const normalized = normalizeForTextRules(line);

  return Boolean(
    /^(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b/.test(normalized) ||
      /^(la actual|la internarea|revine|se revine|control|reevaluare|la reevaluare)\b/.test(normalized) ||
      /^(hemograma|biochimie|coagulare|rx cp|ecografie|eco abd|eco|ct|rmn|irm|ecg|ekg)\s*:/.test(
        normalized
      ) ||
      /^(consult cardiologic|consult neurologic|consult|tratament|flebotomie|s-a efectuat|s-au efectuat|continua tratamentul|acuza)\b/.test(
        normalized
      ) ||
      /^(pbmo|jak homozigot|sat ?o2|beta2 microglobulina)\b/.test(normalized) ||
      /^(hb|ht|l:|ldh|ac uric|splina)\b/.test(normalized)
  );
}

function isListOrMeasurementLine(line: string) {
  const normalized = normalizeForTextRules(line);

  return Boolean(
    /^[-•]/.test(line.trim()) ||
      /^(hb|ht|l:|ldh|ac uric|splina|fal|epo|ta=|av=)\b/.test(normalized) ||
      /^[a-z]{1,4}\s*[:=]\s*\d/.test(normalized)
  );
}

function shouldKeepLineBreak(previousLine: string, currentLine: string) {
  const previous = cleanDisplayLine(previousLine);
  const current = cleanDisplayLine(currentLine);

  if (!previous || !current) return true;
  if (isSeparatorLine(previous) || isSeparatorLine(current)) return true;
  if (isMajorSectionHeading(previous) || isMajorSectionHeading(current)) return true;

  if (/^\[[^\]]+\]$/.test(previous)) return true;

  if (startsNewClinicalThought(current)) return true;

  if (isListOrMeasurementLine(current) && previous.length < 45) return true;

  if (/^(da|nu)$/i.test(current)) return true;

  return false;
}

function joinLines(previousLine: string, currentLine: string) {
  const previous = previousLine.trimEnd();
  const current = currentLine.trimStart();

  if (!previous) return current;
  if (!current) return previous;

  // Fix wrapped hyphenated medical text like "HD C6-\nC7 stg."
  if (previous.endsWith("-")) {
    return `${previous}${current}`;
  }

  return `${previous} ${current}`;
}

export function formatPdfLikeText(value?: string | null) {
  const raw = String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  if (!raw) return "";

  const sourceLines = raw.split("\n");
  const outputLines: string[] = [];

  for (const rawLine of sourceLines) {
    const line = cleanDisplayLine(rawLine);

    if (!line) {
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

    if (!previous || shouldKeepLineBreak(previous, line)) {
      outputLines.push(line);
    } else {
      outputLines[outputLines.length - 1] = joinLines(previous, line);
    }
  }

  return outputLines
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}