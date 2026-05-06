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

export function cleanOneLine(value?: string | null) {
  if (!value) return "";

  return String(value)
    .normalize("NFKC")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeForMatching(value?: string | null) {
  return stripDiacritics(cleanOneLine(value).toLowerCase());
}

function removeKnownPrintNoise(text: string) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => {
      const normalized = normalizeForMatching(line);

      if (!normalized) return true;

      if (normalized.includes("hipocrate - imprimare fisa")) return false;
      if (normalized.includes("biletexternare.asp")) return false;
      if (/^https?:\/\//i.test(normalized)) return false;
      if (/^192\.168\./i.test(normalized)) return false;
      if (/^\d+\s*\/\s*\d+$/.test(normalized)) return false;
      if (/^\d{1,2}\/\d{1,2}\/\d{2,4},?\s+\d{1,2}:\d{2}/.test(normalized)) return false;

      return true;
    })
    .join("\n");
}

function fixCommonOcrArtifacts(text: string) {
  return text
    .replace(/\u00a0/g, " ")
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/[–—−]/g, "-")
    .replace(/Â/g, "")
    .replace(/â€™/g, "'")
    .replace(/â€œ/g, '"')
    .replace(/â€\x9d/g, '"')
    .replace(/\bAPPT\b/g, "APTT")
    .replace(/\bHg (?=\d)/g, "Hb ")
    .replace(/\bHT\b/g, "Ht")
    .replace(/\bPLT\b/g, "Plt")
    .replace(/\bplt\b/g, "Plt")
    .replace(/\bpresent\b/gi, "prezent")
    .replace(/\bPresent\b/g, "Prezent")
    .replace(/\bopion\b/gi, "opinion")
    .replace(/\btratramentului\b/gi, "tratamentului")
    .replace(/\bCreatnina\b/gi, "Creatinina")
    .replace(/\bepisatxis\b/gi, "epistaxis")
    .replace(/\btratamentului cu Hydreea\b/gi, "tratamentului cu Hydrea")
    .replace(/\btratamentului cu Hydree\b/gi, "tratamentului cu Hydrea")
    .replace(/\bRp Hydreea\b/gi, "Rp Hydrea")
    .replace(/\bRp Hydree\b/gi, "Rp Hydrea")
    .replace(/\bcuu\b/gi, "cu")
    .replace(/\s+,/g, ",")
    .replace(/,\s*,/g, ",")
    .replace(/\s+;/g, ";")
    .replace(/\s+\./g, ".")
    .replace(/([A-Za-zĂÂÎȘȚăâîșț])\.([A-ZĂÂÎȘȚ])/g, "$1. $2");
}

function shouldJoinWithPrevious(previous: string, current: string) {
  const prev = previous.trim();
  const cur = current.trim();

  if (!prev || !cur) return false;

  const prevNorm = normalizeForMatching(prev);
  const curNorm = normalizeForMatching(cur);

  if (/[-:,;(/]$/.test(prev)) return true;

  if (/^(ecografiei|caboti?|m4|m5|m6|m7|m8|sap?t\.?|sapt|c7 stg\.?|cov 2 negativ\.?)$/i.test(curNorm)) {
    return true;
  }

  if (/^[a-zăâîșț]/.test(cur) && !/^(la |revine|reevaluare|internare|hemograma|biochimie|coagulare|paraclinic|ecografie|consult|concluzie|tratament|s-au|se |continua|rx |ekg|ngs|fsp|fl:|fs\/)/i.test(cur)) {
    return true;
  }

  if (/^(M\d+|Mbl\d+|Mt\d+|N\d+|S\d+|E\d+|B\d+|L\d+)$/i.test(cur)) {
    return true;
  }

  if (/^(COV 2 negativ|ecografiei)\.?$/i.test(cur)) {
    return true;
  }

  return false;
}

function isMajorClinicalStart(line: string) {
  const normalized = normalizeForMatching(line);

  return (
    /^la\s+(actualul\s+)?(control|reevaluarea|internarea|actuala\s+prezentare)/i.test(normalized) ||
    /^revine\b/i.test(normalized) ||
    /^reevaluare\b/i.test(normalized) ||
    /^re-evaluare\b/i.test(normalized) ||
    /^internare\b/i.test(normalized) ||
    /^\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\s*:/i.test(normalized) ||
    /^\d{1,2}[-./]\d{1,2}[-./]\d{4}\s*:/i.test(normalized)
  );
}

function isSectionLikeLine(line: string) {
  const normalized = normalizeForMatching(line);

  return (
    /^hemograma\s*:/i.test(normalized) ||
    /^biochimie\s*:/i.test(normalized) ||
    /^coagulare\s*:/i.test(normalized) ||
    /^coagulograma\s*:/i.test(normalized) ||
    /^paraclinic\s*:/i.test(normalized) ||
    /^ecografie\b/i.test(normalized) ||
    /^consult\b/i.test(normalized) ||
    /^rx\b/i.test(normalized) ||
    /^ekg\b/i.test(normalized) ||
    /^fsp\s*:/i.test(normalized) ||
    /^fl\s*:/i.test(normalized) ||
    /^fs\//i.test(normalized) ||
    /^ngs\b/i.test(normalized) ||
    /^concluzii?\s*:/i.test(normalized) ||
    /^tratament\s*:/i.test(normalized) ||
    /^diagnostic\b/i.test(normalized)
  );
}

function isShortValueListLine(line: string) {
  const normalized = normalizeForMatching(line);

  if (normalized.length > 90) return false;

  return (
    /^(hb|ht|hct|leuc|l[:=]|plt|tr|trombocite|ldh|crp|fal|epo|sato2|spo2|ta|av|inr|fbg|aptt|splina|ac uric|jak)\b/i.test(
      normalized
    ) ||
    /^[-•]\s*/.test(line.trim())
  );
}

function compactPdfLines(text: string) {
  const sourceLines = text
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  const lines: string[] = [];

  for (const rawLine of sourceLines) {
    let line = rawLine
      .replace(/\s+/g, " ")
      .replace(/\bHD C6-\s+C7\b/gi, "HD C6-C7")
      .replace(/\bcardio-\s+respirator\b/gi, "cardio-respirator")
      .replace(/\bhepato-\s*splenomegalie\b/gi, "hepatosplenomegalie")
      .trim();

    if (!line) continue;

    const previous = lines[lines.length - 1];

    if (previous && shouldJoinWithPrevious(previous, line)) {
      lines[lines.length - 1] = `${previous.replace(/\s+$/, "")} ${line}`;
      continue;
    }

    lines.push(line);
  }

  return lines;
}

export function formatPdfLikeDischargeText(value?: string | null) {
  if (!value) return "";

  let text = String(value).normalize("NFKC");
  text = removeKnownPrintNoise(text);
  text = fixCommonOcrArtifacts(text);

  const lines = compactPdfLines(text);
  const output: string[] = [];

  for (const line of lines) {
    const previous = output[output.length - 1] || "";

    const shouldAddBlankBefore =
      output.length > 0 &&
      isMajorClinicalStart(line) &&
      previous.trim() !== "" &&
      !isMajorClinicalStart(previous);

    if (shouldAddBlankBefore) {
      output.push("");
    }

    output.push(line);
  }

  return output
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function formatSectionPreview(value?: string | null) {
  const text = formatPdfLikeDischargeText(value).replace(/\s+/g, " ").trim();

  if (!text) return "No extracted text.";
  if (text.length <= 92) return text;

  return `${text.slice(0, 92)}...`;
}

export function isAdmissionSummarySection(key?: string | null, title?: string | null) {
  const normalized = normalizeForMatching(`${key || ""} ${title || ""}`);

  return (
    normalized.includes("pre_epicriza") ||
    normalized.includes("admission") ||
    normalized.includes("patient") ||
    normalized.includes("administrative") ||
    normalized.includes("diagnoses") ||
    normalized.includes("diagnostic")
  );
}

function splitBracketedSections(text: string) {
  const lines = formatPdfLikeDischargeText(text).split("\n");
  const sections: { title: string; body: string[] }[] = [];

  let currentTitle = "Details";
  let currentBody: string[] = [];

  function flush() {
    if (currentBody.length) {
      sections.push({
        title: currentTitle,
        body: currentBody,
      });
    }
  }

  for (const line of lines) {
    const match = line.match(/^\[(.+?)\]\s*$/);

    if (match) {
      flush();
      currentTitle = match[1].trim();
      currentBody = [];
      continue;
    }

    currentBody.push(line);
  }

  flush();

  return sections;
}

function splitKeyValueRows(body: string) {
  const rows: AdmissionCardRow[] = [];
  const lines = body.split("\n").map((line) => line.trim()).filter(Boolean);

  for (const line of lines) {
    const colonMatch = line.match(/^([^:]{2,80}):\s*(.+)$/);

    if (colonMatch) {
      rows.push({
        label: cleanOneLine(colonMatch[1]),
        value: cleanOneLine(colonMatch[2]),
      });
      continue;
    }

    rows.push({
      label: "Text",
      value: line,
    });
  }

  return rows;
}

export function splitAdmissionCards(value?: string | null): AdmissionCard[] {
  if (!value) return [];

  const sections = splitBracketedSections(value);

  return sections.map((section) => {
    const rawBody = section.body.join("\n").trim();

    return {
      title: section.title,
      rows: splitKeyValueRows(rawBody),
      rawBody,
    };
  });
}

/**
 * Kept for older imports. The new discharge reader should use formatPdfLikeDischargeText.
 */
export function formatDischargeParagraphs(value?: string | null): DischargeParagraph[] {
  const text = formatPdfLikeDischargeText(value);

  if (!text) return [];

  return text
    .split(/\n{2,}|\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const normalized = normalizeForMatching(line);

      let kind: DischargeParagraphKind = "plain";

      if (isMajorClinicalStart(line)) kind = "clinical_event";
      else if (isSectionLikeLine(line) || isShortValueListLine(line)) kind = "lab_line";
      else if (/\b(hydrea|hydree|ruxolitinib|fedratinib|deferasirox|aspenter|rp\.?|tratament)\b/i.test(normalized)) {
        kind = "medication";
      } else if (/\b(se recomanda|continua|reevaluare|control)\b/i.test(normalized)) {
        kind = "recommendation";
      }

      return {
        text: line,
        kind,
      };
    });
}