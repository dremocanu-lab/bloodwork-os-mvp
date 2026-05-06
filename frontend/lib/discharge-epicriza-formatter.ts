export type DischargeParagraphKind =
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

export function cleanOneLine(value?: string | number | null) {
  if (value === null || value === undefined) return "";

  return String(value)
    .normalize("NFKC")
    .replace(/\u00a0/g, " ")
    .replace(/\ufeff/g, "")
    .replace(/[ \t]+/g, " ")
    .trim();
}

export function normalizeDischargeText(value?: string | null) {
  if (!value) return "";

  let text = String(value)
    .normalize("NFKC")
    .replace(/\u00a0/g, " ")
    .replace(/\ufeff/g, "")
    .replace(/Â·/g, "·")
    .replace(/Â/g, "")
    .replace(/â€™/g, "'")
    .replace(/â€œ/g, '"')
    .replace(/â€\u009d/g, '"')
    .replace(/â€“/g, "-")
    .replace(/â€”/g, "-")
    .replace(/−/g, "-")
    .replace(/–/g, "-")
    .replace(/—/g, "-");

  text = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  text = text.replace(/[ \t]+\n/g, "\n");
  text = text.replace(/\n{4,}/g, "\n\n\n");

  return text.trim();
}

function normalizeForMatch(value?: string | null) {
  return stripDiacritics(cleanOneLine(value || "").toLowerCase());
}

function isJunkLine(line: string) {
  const normalized = normalizeForMatch(line);

  if (!normalized) return true;

  if (/^hipocrate\s*-\s*imprimare\s*fisa$/.test(normalized)) return true;
  if (/^epicriza$/.test(normalized)) return true;
  if (/^bilet\s+de\s+iesire/.test(normalized)) return true;
  if (/^scrisoare\s+medicala/.test(normalized)) return true;
  if (/^pagina\s+\d+/.test(normalized)) return true;
  if (/^\d+\s*\/\s*\d+$/.test(normalized)) return true;
  if (/^page\s+\d+/.test(normalized)) return true;
  if (/^192\.168\./.test(normalized)) return true;
  if (/biletexternare\.asp/.test(normalized)) return true;
  if (/relid=|relld=|relname=/.test(normalized)) return true;

  // Browser/PDF viewer timestamp junk.
  if (/^\d{1,2}\/\d{1,2}\/\d{2,4},?\s+\d{1,2}:\d{2}\s*(am|pm)?$/i.test(line.trim())) {
    return true;
  }

  return false;
}

function applySafeMedicalCorrections(value: string) {
  let text = value;

  const replacements: Array<[RegExp, string]> = [
    [/\bΕΡΟ\b/g, "EPO"],
    [/\bEΡO\b/g, "EPO"],
    [/\bΕPO\b/g, "EPO"],
    [/\bHydreea\b/gi, "Hydrea"],
    [/\bHydree\b/gi, "Hydrea"],
    [/\bAPPT\b/g, "APTT"],
    [/\bafebrile\b/gi, "afebril"],
    [/\bpresent\b/gi, "prezent"],
    [/\bpaloaere\b/gi, "paloare"],
    [/\btratramentului\b/gi, "tratamentului"],
    [/\btrtament\b/gi, "tratament"],
    [/\bopion\b/gi, "opinion"],
  ];

  replacements.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });

  return text;
}

function startsLikeMajorMedicalLine(line: string) {
  const normalized = normalizeForMatch(line);

  return (
    /^(la diagnostic|tratament|pbmo|jak|din aprilie|in ultima perioada|la actuala prezentare|revine|la internarea|la actualul control|la reevaluarea|reevaluare|internare|pacientul revine|ex obiectiv|consult|ecografie|hemograma|biochimie|coagulare|coagulograma|rx cp|ekg|ecg|paraclinic|frotiu|fsp|fl|ngs|concluzie|concluzii|diagnostic|se recomanda|s-au administrat|s-a administrat|s-a efectuat|s-a eliberat|continua tratamentul|rp\.?|clearance creatinina|medic rezident|in perioada|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}:|\d{1,2}\s*-\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}:)/i.test(
      normalized
    )
  );
}

function startsLikeIndentedListLine(line: string) {
  const trimmed = line.trim();

  return (
    /^[-•]/.test(trimmed) ||
    /^(Hb|Ht|Hct|L|Leuc|Tr|Plt|FAL|LDH|AST|ALT|Cr|Creat|CRP|INR|Fbg|APTT|TA|AV|SatO2|SpO2|VP|RD|RS|FL|FS|FSP)\b/i.test(
      trimmed
    )
  );
}

function endsLikeCompleteSentence(line: string) {
  const trimmed = line.trim();

  if (!trimmed) return false;

  if (/[.!?)]$/.test(trimmed)) return true;

  // Medical shorthand often ends complete without punctuation.
  if (/\b(OTS|incident[e]?|normale|normal|prezenta|prezent|absenta|absent|buna|bună|afebril)\.?$/i.test(trimmed)) {
    return true;
  }

  return false;
}

function shouldJoinWithNext(current: string, next: string) {
  const a = current.trim();
  const b = next.trim();

  if (!a || !b) return false;
  if (isJunkLine(a) || isJunkLine(b)) return false;

  // Never join new major medical events onto previous lines.
  if (startsLikeMajorMedicalLine(b)) return false;

  // Keep intentional lab/list rows on their own line.
  if (startsLikeIndentedListLine(b)) return false;

  // If next line starts lowercase, it is usually a wrapped continuation.
  if (/^[a-zăâîșț]/.test(b)) return true;

  // If previous line ends mid-phrase, join.
  if (/[,:;(-]$/.test(a)) return true;

  // If previous line is short and next continues without a new label, join.
  if (a.length < 55 && !endsLikeCompleteSentence(a)) return true;

  // OCR/PDF wraps long prose lines; join if previous does not look complete.
  if (!endsLikeCompleteSentence(a) && b.length > 20) return true;

  return false;
}

function cleanPdfLikeLines(value?: string | null) {
  const raw = normalizeDischargeText(value);

  if (!raw) return [];

  const lines = raw
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trimEnd())
    .filter((line) => !isJunkLine(line));

  const corrected = lines.map((line) => applySafeMedicalCorrections(line));

  return corrected;
}

export function formatPdfLikeDischargeText(value?: string | null) {
  const lines = cleanPdfLikeLines(value);

  if (!lines.length) return "";

  const result: string[] = [];

  for (const line of lines) {
    const current = line.trim();

    if (!current) continue;

    if (!result.length) {
      result.push(current);
      continue;
    }

    const previous = result[result.length - 1];

    if (shouldJoinWithNext(previous, current)) {
      result[result.length - 1] = `${previous.replace(/\s+$/, "")} ${current.replace(/^\s+/, "")}`;
      continue;
    }

    result.push(current);
  }

  let text = result.join("\n");

  // Add light breathing room before true timeline/event starts, without destroying PDF-like layout.
  text = text.replace(
    /\n(La reevaluarea|Reevaluare|La internarea|Internare|La actualul control|Revine la internare|Revine \()/g,
    "\n\n$1"
  );

  text = text.replace(/\n{4,}/g, "\n\n\n");

  return text.trim();
}

export function formatSectionPreview(value?: string | null) {
  const text = formatPdfLikeDischargeText(value || "").replace(/\s+/g, " ").trim();

  if (!text) return "No extracted text.";

  if (text.length <= 92) return text;

  return `${text.slice(0, 92)}...`;
}

function classifyParagraphKind(text: string): DischargeParagraphKind {
  const normalized = normalizeForMatch(text);

  if (/^(diagnostic|epicriza|tratament|recomandari|investigatii|stare la externare)/.test(normalized)) {
    return "heading";
  }

  if (/^(hemograma|biochimie|coagulare|coagulograma|paraclinic|fl|fsp|ldh|hb|ht|hct|leuc|tr|plt|rx cp|ecografie|ekg|ecg)/.test(normalized)) {
    return "lab_line";
  }

  if (/\b(hydrea|fedratinib|deferasirox|aspenter|ruxolitinib|mydocalm|movalis|alanerv|rp\.?)\b/i.test(normalized)) {
    return "medication";
  }

  if (/^(se recomanda|recomand|continua tratamentul|reevaluare|control)/.test(normalized)) {
    return "recommendation";
  }

  if (/^(la reevaluarea|reevaluare|la internarea|internare|la actualul control|revine)/.test(normalized)) {
    return "clinical_event";
  }

  return "plain";
}

// Kept for compatibility with the current page import.
// The new reader should mostly use formatPdfLikeDischargeText instead.
export function formatDischargeParagraphs(value?: string | null): DischargeParagraph[] {
  const formatted = formatPdfLikeDischargeText(value);

  if (!formatted) return [];

  return formatted
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((text) => ({
      text,
      kind: classifyParagraphKind(text),
    }));
}

export function isAdmissionSummarySection(key?: string | null, title?: string | null) {
  const normalizedKey = normalizeForMatch(key || "");
  const normalizedTitle = normalizeForMatch(title || "");

  return (
    normalizedKey === "pre_epicriza_summary" ||
    normalizedKey === "administrative_information" ||
    normalizedTitle.includes("admission") ||
    normalizedTitle.includes("patient") ||
    normalizedTitle.includes("diagnoses") ||
    normalizedTitle.includes("diagnostic")
  );
}

function parseBracketedSectionBlocks(value?: string | null) {
  const text = normalizeDischargeText(value);

  if (!text) return [];

  const blocks: Array<{ title: string; body: string }> = [];
  const lines = text.split("\n");

  let currentTitle = "Details";
  let currentLines: string[] = [];

  function flush() {
    const body = currentLines.join("\n").trim();

    if (body) {
      blocks.push({
        title: currentTitle,
        body,
      });
    }

    currentLines = [];
  }

  lines.forEach((line) => {
    const match = line.trim().match(/^\[(.+?)\]$/);

    if (match) {
      flush();
      currentTitle = cleanOneLine(match[1]) || "Details";
      return;
    }

    currentLines.push(line);
  });

  flush();

  return blocks;
}

function splitLabelValueLines(body: string) {
  const rows: AdmissionCardRow[] = [];
  const lines = formatPdfLikeDischargeText(body)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  lines.forEach((line) => {
    const colonMatch = line.match(/^([^:]{2,80}):\s*(.+)$/);

    if (colonMatch) {
      rows.push({
        label: cleanOneLine(colonMatch[1]),
        value: cleanOneLine(colonMatch[2]),
      });
      return;
    }

    const dashMatch = line.match(/^([A-ZĂÂÎȘȚa-zăâîșț0-9 /().-]{2,80})\s+-\s+(.+)$/);

    if (dashMatch) {
      rows.push({
        label: cleanOneLine(dashMatch[1]),
        value: cleanOneLine(dashMatch[2]),
      });
      return;
    }

    rows.push({
      label: "Detail",
      value: line,
    });
  });

  return rows;
}

export function splitAdmissionCards(value?: string | null): AdmissionCard[] {
  const blocks = parseBracketedSectionBlocks(value);

  if (blocks.length) {
    return blocks.map((block) => ({
      title: block.title,
      rows: splitLabelValueLines(block.body),
      rawBody: block.body,
    }));
  }

  const body = normalizeDischargeText(value);

  if (!body) return [];

  return [
    {
      title: "Admission / patient / diagnoses",
      rows: splitLabelValueLines(body),
      rawBody: body,
    },
  ];
}