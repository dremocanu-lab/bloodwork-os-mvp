Im showerinexport type DischargeParagraphKind =
  | "heading"
  | "clinical_event"
  | "lab_line"
  | "medication"
  | "recommendation"
  | "plain";

export type DischargeParagraph = {
  text: string;
  kind: DischargeParagraphKind;
};

export type AdmissionCardRow = {
  label: string;
  value: string;
};

export type AdmissionCard = {
  title: string;
  rows: AdmissionCardRow[];
  rawBody: string;
};

function stripDiacritics(value: string) {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ș/g, "s")
    .replace(/ț/g, "t")
    .replace(/ă/g, "a")
    .replace(/â/g, "a")
    .replace(/î/g, "i")
    .replace(/Ș/g, "S")
    .replace(/Ț/g, "T")
    .replace(/Ă/g, "A")
    .replace(/Â/g, "A")
    .replace(/Î/g, "I");
}

export function normalizeDischargeText(value?: string | null) {
  if (!value) return "";

  let text = String(value)
    .normalize("NFKC")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/\ufeff/g, "")
    .replace(/Â·/g, "·")
    .replace(/Â/g, "")
    .replace(/â€™/g, "'")
    .replace(/â€œ/g, '"')
    .replace(/â€\x9d/g, '"')
    .replace(/â€“|â€”/g, "-")
    .replace(/−|–|—/g, "-")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  const noisePatterns = [
    /^\s*\d+\s*\/\s*\d+\s*$/i,
    /^\s*\d{1,2}\/\d{1,2}\/\d{2,4},?\s+\d{1,2}:\d{2}\s*(AM|PM)?\s*$/i,
    /^hipocrate\s*-\s*imprimare\s+fi[sș]a$/i,
    /192\.168\./i,
    /biletexternare\.asp/i,
    /relid=/i,
    /relld=/i,
    /relname=/i,
  ];

  text = text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !noisePatterns.some((pattern) => pattern.test(line)))
    .join("\n");

  const replacements: Array<[RegExp, string]> = [
    [/\bHg(?=\s*\d)/gi, "Hb"],
    [/\bAPPT\b/gi, "APTT"],
    [/\bHydree\b/gi, "Hydrea"],
    [/\bHya\b/gi, "Hydrea"],
    [/\bHydreea\b/gi, "Hydrea"],
    [/\bDefserasirox\b/gi, "Deferasirox"],
    [/\bDeferasiox\b/gi, "Deferasirox"],
    [/\bg\/dl\b/gi, "g/dL"],
    [/\bmg\/dl\b/gi, "mg/dL"],
    [/\bmg\/l\b/gi, "mg/L"],
    [/\bu\/l\b/gi, "U/L"],
    [/\bmmol\/l\b/gi, "mmol/L"],
    [/\bmmc\b/gi, "mmc"],
    [/\s+([,.;:])/g, "$1"],
    [/([,.;:])([^\s])/g, "$1 $2"],
  ];

  for (const [pattern, replacement] of replacements) {
    text = text.replace(pattern, replacement);
  }

  return text.replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}

export function cleanOneLine(value?: string | null) {
  return normalizeDischargeText(value).replace(/\s+/g, " ").trim();
}

export function formatSectionPreview(value?: string | null, limit = 86) {
  const text = cleanOneLine(value);

  if (!text) return "No extracted text.";
  if (text.length <= limit) return text;

  return `${text.slice(0, limit)}...`;
}

function normalizedLine(value: string) {
  return stripDiacritics(cleanOneLine(value)).toLowerCase();
}

export function isAdmissionSummarySection(key?: string, title?: string) {
  const normalized = normalizedLine(`${key || ""} ${title || ""}`);

  return (
    normalized.includes("pre_epicriza_summary") ||
    normalized.includes("administrative") ||
    normalized.includes("admission / patient / diagnoses") ||
    normalized.includes("administrative / admission information")
  );
}

export function isMajorClinicalStart(line: string) {
  const normalized = normalizedLine(line);

  return (
    /^la\s+(actuala|actualul|internarea|reevaluarea|controlul)/i.test(normalized) ||
    /^revine\b/i.test(normalized) ||
    /^hemograma\s*:/i.test(normalized) ||
    /^biochimie\s*:/i.test(normalized) ||
    /^coagulare\s*:/i.test(normalized) ||
    /^consult\s+/i.test(normalized) ||
    /^rx\s+/i.test(normalized) ||
    /^eco\s+/i.test(normalized) ||
    /^ecografie\s+/i.test(normalized) ||
    /^ct\s+/i.test(normalized) ||
    /^rmn\s+/i.test(normalized) ||
    /^tratament\s*:/i.test(normalized) ||
    /^diagnostic/i.test(normalized) ||
    /^stare\s+la\s+externare/i.test(normalized) ||
    /^recomand/i.test(normalized) ||
    /^indicatii/i.test(normalized) ||
    /^s-a\s+/i.test(normalized) ||
    /^s-au\s+/i.test(normalized) ||
    /^continua\b/i.test(normalized) ||
    /^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}/.test(normalized)
  );
}

function isLikelyWrappedContinuation(previous: string, current: string) {
  if (!previous) return false;
  if (isMajorClinicalStart(current)) return false;

  const previousEndsHard = /[.;:!?)]$/.test(previous.trim());
  const currentStartsLower = /^[a-zăâîșț]/.test(current.trim());

  if (!previousEndsHard && previous.length >= 60) return true;
  if (currentStartsLower && current.length < 120) return true;
  if (/^(normal|prezent|fara|cu|de|la|in|si|sau|mmHg|mg\/dL|g\/dL)/i.test(current)) return true;

  return false;
}

function classifyParagraph(text: string): DischargeParagraphKind {
  const normalized = normalizedLine(text);

  if (/^[A-ZĂÂÎȘȚ0-9 /\-.]{6,}$/.test(text) && text.length < 90) {
    return "heading";
  }

  if (
    /^hemograma\s*:/.test(normalized) ||
    /^biochimie\s*:/.test(normalized) ||
    /^coagulare\s*:/.test(normalized) ||
    /\b(hb|ht|leucocite|trombocite|plt|ldh|crp|uree|creatinina|glucoza|fibrinogen|inr|ast|alt|bilirubina|colesterol|trigliceride|mg\/dl|g\/dl|u\/l|mmc)\b/.test(
      normalized
    )
  ) {
    return "lab_line";
  }

  if (
    /\b(hydrea|aspenter|mydocalm|movalis|alanerv|deferasirox|comprimate|capsule|cp\/zi|mg|ml|tratament|reteta|rp)\b/.test(
      normalized
    )
  ) {
    return "medication";
  }

  if (
    /^recomand/.test(normalized) ||
    /^indicatii/.test(normalized) ||
    /\b(control|monitorizare|revine|regim|follow-up|follow up)\b/.test(normalized)
  ) {
    return "recommendation";
  }

  if (isMajorClinicalStart(text)) return "clinical_event";

  return "plain";
}

export function formatDischargeParagraphs(value?: string | null): DischargeParagraph[] {
  const text = normalizeDischargeText(value);

  if (!text) return [];

  const rawLines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const paragraphs: string[] = [];

  for (const line of rawLines) {
    const previous = paragraphs[paragraphs.length - 1] || "";

    if (!paragraphs.length) {
      paragraphs.push(line);
      continue;
    }

    if (isLikelyWrappedContinuation(previous, line)) {
      paragraphs[paragraphs.length - 1] = `${previous} ${line}`.replace(/\s+/g, " ").trim();
      continue;
    }

    paragraphs.push(line);
  }

  return paragraphs.map((paragraph) => ({
    text: paragraph,
    kind: classifyParagraph(paragraph),
  }));
}

function blockTitleFromKey(title: string) {
  const normalized = normalizedLine(title);

  if (normalized.includes("administrative")) return "Hospital / admission details";
  if (normalized.includes("discharge status")) return "Discharge status";
  if (normalized.includes("diagnos")) return "Diagnoses";
  if (normalized.includes("patient")) return "Patient identity";

  return title || "Details";
}

export function splitAdmissionCards(value?: string | null): AdmissionCard[] {
  const text = normalizeDischargeText(value);

  if (!text) return [];

  const bracketMatches = Array.from(
    text.matchAll(/\[([^\]]+)\]\n([\s\S]*?)(?=\n\n\[[^\]]+\]\n|$)/g)
  );

  const rawBlocks = bracketMatches.length
    ? bracketMatches.map((match) => ({
        title: blockTitleFromKey(cleanOneLine(match[1])),
        body: normalizeDischargeText(match[2]),
      }))
    : [
        {
          title: "Admission / patient / diagnoses",
          body: text,
        },
      ];

  return rawBlocks
    .map((block) => ({
      title: block.title,
      rawBody: block.body,
      rows: extractRowsFromAdmissionBlock(block.body),
    }))
    .filter((block) => block.rows.length || block.rawBody);
}

function extractRowsFromAdmissionBlock(value?: string | null): AdmissionCardRow[] {
  const text = normalizeDischargeText(value);

  if (!text) return [];

  const rows: AdmissionCardRow[] = [];
  const looseLines: string[] = [];

  const lines = text
    .split("\n")
    .map((line) => cleanOneLine(line))
    .filter(Boolean);

  for (const line of lines) {
    const colonMatch = line.match(/^([^:]{2,64}):\s*(.+)$/);

    if (colonMatch) {
      rows.push({
        label: colonMatch[1].trim(),
        value: colonMatch[2].trim(),
      });
      continue;
    }

    const datePeriodMatch = line.match(
      /(perioada\s+intern[aă]rii|perioada\s+de\s+internare)\s*(.+)$/i
    );

    if (datePeriodMatch) {
      rows.push({
        label: "Perioada internării",
        value: datePeriodMatch[2].trim(),
      });
      continue;
    }

    const diagnosisCodeMatch = line.match(/^([A-Z]\d{2}(?:\.\d+)?\*?)\s+(.+)$/);

    if (diagnosisCodeMatch) {
      rows.push({
        label: diagnosisCodeMatch[1],
        value: diagnosisCodeMatch[2],
      });
      continue;
    }

    const upperLabelMatch = line.match(/^([A-ZĂÂÎȘȚ0-9 /\-.]{4,70})\s+(.+)$/);

    if (upperLabelMatch && upperLabelMatch[1].trim().length <= 48) {
      rows.push({
        label: upperLabelMatch[1].trim(),
        value: upperLabelMatch[2].trim(),
      });
      continue;
    }

    looseLines.push(line);
  }

  if (looseLines.length) {
    rows.push({
      label: "Details",
      value: looseLines.join("\n"),
    });
  }

  return rows;
}