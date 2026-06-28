export function getHomeByRole(role: string): string {
  if (role === "patient") return "/my-records";
  if (role === "doctor") return "/my-patients";
  if (role === "care_partner") return "/care-partner";
  return "/assignments";
}
