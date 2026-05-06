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