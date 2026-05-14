import type { AppLanguage } from "@/lib/i18n";

export function formatPatientAge(
  dateOfBirth: string | null | undefined,
  language: AppLanguage = "en",
): string {
  if (!dateOfBirth) return "—";

  const dob = new Date(dateOfBirth);
  if (Number.isNaN(dob.getTime())) return "—";

  const today = new Date();
  let years = today.getFullYear() - dob.getFullYear();
  let months = today.getMonth() - dob.getMonth();

  if (today.getDate() < dob.getDate()) months -= 1;
  if (months < 0) { years -= 1; months += 12; }
  if (years < 0) return "—";

  if (language === "ro") return `${years}a ${months}l`;
  return `${years}y ${months}m`;
}
