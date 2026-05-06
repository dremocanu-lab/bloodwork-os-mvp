export function cleanOneLine(value?: string | null) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

export function formatSectionPreview(value?: string | null) {
  const text = cleanOneLine(value);

  if (!text) return "No extracted text.";
  if (text.length <= 110) return text;

  return `${text.slice(0, 110)}...`;
}

function protectMedicalAbbreviations(text: string) {
  return text
    .replace(/\bF\.\s*O\./gi, "F.O.")
    .replace(/\bDr\.\s+/g, "Dr. ")
    .replace(/\bS\.\s*Nicolau/g, "S. Nicolau")
    .replace(/\bp\.\s*Cys/gi, "p.Cys")
    .replace(/\bC\.\s*Difficile/gi, "C.Difficile")
    .replace(/\bAg\.\s*Rotavirus/gi, "Ag.Rotavirus")
    .replace(/\bSd\.\s*Diareic/gi, "Sd.Diareic")
    .replace(/\bRp\.\s+/g, "Rp. ")
    .replace(/\bEx\.\s+obiectiv/gi, "Ex. obiectiv")
    .replace(/\bFSP:\s*/gi, "FSP: ")
    .replace(/\bFSN:\s*/gi, "FSN: ")
    .replace(/\bFL:\s*/gi, "FL: ");
}

function normalizeMedicationNames(text: string) {
  return text
    .replace(/\bHydreea\b/gi, "Hydrea")
    .replace(/\bHydree\b/gi, "Hydrea")
    .replace(/\bHydrea\b/g, "Hydrea")
    .replace(/\bFeratinib\b/gi, "Fedratinib")
    .replace(/\bFedratinib\b/g, "Fedratinib")
    .replace(/\bRuxolitinib\b/g, "Ruxolitinib")
    .replace(/\bJakavi\b/g, "Jakavi");
}

function normalizeCommonOcr(text: string) {
  return text
    .replace(/\bHg\s+(\d)/g, "Hb $1")
    .replace(/\bHT\s+/g, "Ht ")
    .replace(/\bHCT\s+/g, "Hct ")
    .replace(/\bPLT\b/g, "Plt")
    .replace(/\bPlt\b/g, "Plt")
    .replace(/\bTr\.\s+/g, "Tr. ")
    .replace(/\bTr\s+/g, "Tr ")
    .replace(/\bAPPT\b/g, "APTT")
    .replace(/\bSatO2\b/g, "SatO2")
    .replace(/\bSp02\b/g, "SpO2")
    .replace(/\bSpO2\s*=\s*/g, "SpO2=")
    .replace(/\bOTS\b/g, "OTS")
    .replace(/\bMEr\b/g, "MEr")
    .replace(/\bMER\b/g, "MEr")
    .replace(/\bUMER\b/g, "UMEr")
    .replace(/\bUMEr\b/g, "UMEr")
    .replace(/\bU ME\b/g, "U ME")
    .replace(/\bU MEr\b/g, "U MEr");
}

function joinBadLineBreaks(text: string) {
  const rawLines = text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd());

  const result: string[] = [];

  const hardStart = /^(La diagnostic:|Tratament:|La actuala prezentare|Revine|La internarea|La actualul control|Reevaluare|Re-evaluare|La reevaluarea|Internare|Clinic:|Hemograma:|Hemoleucograma:|Biochimie:|Coagulare:|Coagulograma:|Paraclinic:|FSP:|FSN:|FL:|Ecografie|Consult|Concluzii?:|Diagnostic|Tratament|Pe parcursul|S-au administrat|S-a administrat|S-a efectuat|Se administreaza|Se recomanda|Se elibereaza|S-a eliberat|Pacientul|NGS|PBO|PBMO|Aspirat medular|Bilant|In data de|In perioada|Frotiu|Medic rezident)/i;

  const bulletStart = /^[-–•]/;
  const previousCanContinue = /[,;:(=\/-]$|(\bsi|\bcu|\bfara|\bla|\bde|\bin|\bprin|\bpentru|\bvs\.|\bsegmentul|\bNeut|\bHb|\bHct|\bVEM|\bHEM|\bTr\.?|\bLDH|\bALT|\bAST|\bCRP)$/i;

  for (const rawLine of rawLines) {
    const line = rawLine.trim();

    if (!line) {
      if (result.length && result[result.length - 1] !== "") result.push("");
      continue;
    }

    if (!result.length) {
      result.push(line);
      continue;
    }

    const previous = result[result.length - 1];

    if (!previous) {
      result.push(line);
      continue;
    }

    const currentLooksLikeNewBlock = hardStart.test(line) || bulletStart.test(line);
    const previousLooksIncomplete = previousCanContinue.test(previous);
    const currentStartsLower = /^[a-zăâîșț]/.test(line);
    const currentIsShortUnitContinuation = /^(SPC|ecografiei|la palpare|M\d|M\d\.|Cabot\.?|Doppler|VIII\.?|RCD|RCS)/i.test(line);

    if (!currentLooksLikeNewBlock && (previousLooksIncomplete || currentStartsLower || currentIsShortUnitContinuation)) {
      result[result.length - 1] = `${previous} ${line}`;
      continue;
    }

    result.push(line);
  }

  return result.join("\n");
}

function addClinicalSpacing(text: string) {
  return text
    .replace(/\n(La actuala prezentare)/g, "\n\n$1")
    .replace(/\n(Revine la internare)/g, "\n\n$1")
    .replace(/\n(La internarea)/g, "\n\n$1")
    .replace(/\n(La actualul control)/g, "\n\n$1")
    .replace(/\n(Reevaluare in data)/g, "\n\n$1")
    .replace(/\n(Re-evaluare in data)/g, "\n\n$1")
    .replace(/\n(La reevaluarea din)/g, "\n\n$1")
    .replace(/\n(Internare\s)/g, "\n\n$1")
    .replace(/\n(\d{2}-\d{2}\.\d{2}\.\d{4}:)/g, "\n\n$1")
    .replace(/\n(\d{2}\.\d{2}\.\d{4}:)/g, "\n\n$1")
    .replace(/\n(\d{2}-\d{2}\.\d{2}\.\d{4})/g, "\n\n$1")
    .replace(/\n(0?\d{1,2}\.\d{2}\.\d{4}:)/g, "\n\n$1")
    .replace(/\n{3,}/g, "\n\n");
}

function normalizeSpacing(text: string) {
  return text
    .replace(/[ \t]+/g, " ")
    .replace(/\s+([,.;:])/g, "$1")
    .replace(/([,;:])(?=\S)/g, "$1 ")
    .replace(/\s+\/\s+/g, "/")
    .replace(/\s*=\s*/g, "=")
    .replace(/\s*->\s*/g, "->")
    .replace(/\s+%/g, "%")
    .replace(/\b(\d+)\s+\/\s+(\d+)\b/g, "$1/$2")
    .replace(/\b(\d+)\s+mg\/dl\b/gi, "$1 mg/dl")
    .replace(/\b(\d+)\s+g\/dl\b/gi, "$1 g/dl")
    .replace(/\b(\d+)\s+U\/L\b/g, "$1 U/L")
    .replace(/\b(\d+)\s+U\/I\b/g, "$1 U/I")
    .replace(/\bF\.\s+O\./g, "F.O.")
    .replace(/\bS\.\s+Nicolau/g, "S. Nicolau");
}

export function formatPdfLikeDischargeText(value?: string | null) {
  if (!value) return "";

  let text = String(value)
    .replace(/\u00a0/g, " ")
    .replace(/[“”]/g, '"')
    .replace(/[’]/g, "'")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");

  text = normalizeSpacing(text);
  text = protectMedicalAbbreviations(text);
  text = normalizeMedicationNames(text);
  text = normalizeCommonOcr(text);
  text = joinBadLineBreaks(text);
  text = addClinicalSpacing(text);
  text = normalizeSpacing(text);

  return text.trim();
}