"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin" | "care_partner";
  department?: string | null;
  hospital_name?: string | null;
};

type DoctorAccess = {
  doctor_user_id: number;
  doctor_name: string;
  doctor_email: string;
  department?: string | null;
  hospital_name?: string | null;
  granted_at: string;
};

type AccessRequest = {
  id: number;
  doctor_user_id: number;
  doctor_name?: string | null;
  doctor_email?: string | null;
  doctor_department?: string | null;
  doctor_hospital_name?: string | null;
  status: string;
  requested_at: string;
  responded_at?: string | null;
};

type CarePartnerLink = {
  care_partner_user_id: number;
  care_partner_name: string;
  care_partner_email: string;
  linked_at: string;
};

type CarePartnerCodeResponse = {
  code: string;
  created_at: string;
};

type MyProfileResponse = {
  patient: { id: number; full_name: string };
  doctor_access: DoctorAccess[];
  sections: Record<string, unknown>;
  events: unknown[];
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function MyAccessPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [doctorAccess, setDoctorAccess] = useState<DoctorAccess[]>([]);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [carePartners, setCarePartners] = useState<CarePartnerLink[]>([]);
  const [carePartnerCode, setCarePartnerCode] = useState<CarePartnerCodeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [revokeTarget, setRevokeTarget] = useState<DoctorAccess | null>(null);
  const [revoking, setRevoking] = useState(false);

  const [respondingId, setRespondingId] = useState<number | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [codeCopied, setCodeCopied] = useState(false);

  async function load() {
    const meResponse = await api.get<CurrentUser>("/auth/me");

    if (meResponse.data.role !== "patient") {
      router.replace(meResponse.data.role === "doctor" ? "/my-patients" : "/assignments");
      return;
    }

    setCurrentUser(meResponse.data);

    const [profileResponse, requestsResponse, carePartnersResponse, codeResponse] =
      await Promise.all([
        api.get<MyProfileResponse>("/my/profile"),
        api.get<AccessRequest[]>("/my/access-requests"),
        api.get<CarePartnerLink[]>("/my/care-partners"),
        api.get<CarePartnerCodeResponse>("/my/care-partner-code"),
      ]);

    setDoctorAccess(profileResponse.data.doctor_access || []);
    setRequests(requestsResponse.data || []);
    setCarePartners(carePartnersResponse.data || []);
    setCarePartnerCode(codeResponse.data);
  }

  useEffect(() => {
    async function init() {
      try {
        await load();
      } catch (err) {
        setError(getErrorMessage(err, "Could not load access data."));
      } finally {
        setLoading(false);
      }
    }
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function respondToRequest(requestId: number, status: "approved" | "denied") {
    try {
      setRespondingId(requestId);
      setError("");
      await api.post(`/access-requests/${requestId}/respond`, { status });
      await load();
    } catch (err) {
      setError(getErrorMessage(err, "Could not respond to request."));
    } finally {
      setRespondingId(null);
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget) return;

    try {
      setRevoking(true);
      setError("");
      await api.delete(`/my/access/${revokeTarget.doctor_user_id}`);
      setRevokeTarget(null);
      await load();
    } catch (err) {
      setError(getErrorMessage(err, "Could not revoke access."));
    } finally {
      setRevoking(false);
    }
  }

  async function regenerateCode() {
    try {
      setRegenerating(true);
      setError("");
      const response = await api.post<CarePartnerCodeResponse>("/my/care-partner-code/regenerate");
      setCarePartnerCode(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not regenerate code."));
    } finally {
      setRegenerating(false);
    }
  }

  function copyCode() {
    if (!carePartnerCode) return;
    navigator.clipboard.writeText(carePartnerCode.code).then(() => {
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), 2000);
    });
  }

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingYourRecords")}</p>
      </main>
    );
  }

  const pendingRequests = requests.filter((r) => r.status === "pending");

  return (
    <AppShell
      user={currentUser}
      title={t("myAccess")}
      subtitle={t("myAccessDesc")}
    >
      {revokeTarget && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            background: "rgba(15, 23, 42, 0.42)",
            display: "grid",
            placeItems: "center",
            padding: 20,
            backdropFilter: "blur(10px)",
          }}
        >
          <div
            className="soft-card"
            style={{ width: "min(480px, 100%)", padding: 24, boxShadow: "0 30px 90px rgba(15,23,42,0.32)" }}
          >
            <div style={{ fontSize: 22, fontWeight: 950, letterSpacing: "-0.05em" }}>
              {t("revokeAccessConfirmTitle")}
            </div>

            <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.65 }}>
              {t("revokeAccessConfirmDesc")}
            </div>

            <div className="soft-card-tight" style={{ marginTop: 16, padding: 14, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>{revokeTarget.doctor_name}</div>
              <div className="muted-text" style={{ marginTop: 4 }}>{revokeTarget.doctor_email}</div>
              <div className="muted-text" style={{ marginTop: 6 }}>
                {valueOrDash(revokeTarget.department)} · {valueOrDash(revokeTarget.hospital_name)}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
              <button
                className="secondary-btn"
                onClick={() => setRevokeTarget(null)}
                disabled={revoking}
              >
                {t("cancel")}
              </button>
              <button
                onClick={confirmRevoke}
                disabled={revoking}
                style={{
                  border: "1px solid var(--danger-border)",
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  borderRadius: 14,
                  padding: "11px 15px",
                  fontWeight: 950,
                  cursor: revoking ? "not-allowed" : "pointer",
                }}
              >
                {revoking ? t("revoking") : t("confirmRevoke")}
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            borderColor: "var(--danger-border)",
            background: "var(--danger-bg)",
            color: "var(--danger-text)",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ display: "grid", gap: 24 }}>
        {/* Care Partner Code */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 18 }}>
            <div className="section-title">{t("carePartnerCode")}</div>
            <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.5 }}>
              {t("carePartnerCodeDesc")}
            </div>
          </div>

          {carePartnerCode ? (
            <div style={{ display: "grid", gap: 16 }}>
              <div
                className="soft-card-tight"
                style={{
                  padding: "18px 20px",
                  background: "var(--panel-2)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 16,
                  flexWrap: "wrap",
                }}
              >
                <div
                  style={{
                    fontFamily: "monospace",
                    fontSize: 28,
                    fontWeight: 900,
                    letterSpacing: "0.1em",
                    color: "var(--primary)",
                  }}
                >
                  {carePartnerCode.code}
                </div>

                <button
                  type="button"
                  className="secondary-btn"
                  onClick={copyCode}
                  style={{ whiteSpace: "nowrap" }}
                >
                  {codeCopied ? t("copied") : t("copyCode")}
                </button>
              </div>

              <div className="muted-text" style={{ fontSize: 12 }}>
                {t("codeGeneratedAt")} {formatDate(carePartnerCode.created_at)}
              </div>

              <div>
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={regenerateCode}
                  disabled={regenerating}
                >
                  {regenerating ? t("working") : t("regenerateCode")}
                </button>
                <div className="muted-text" style={{ marginTop: 6, fontSize: 12 }}>
                  {t("regenerateCodeWarning")}
                </div>
              </div>
            </div>
          ) : (
            <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
              <div className="muted-text">{t("loadingCode")}</div>
            </div>
          )}
        </div>

        {/* Active Care Partners */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 18 }}>
            <div className="section-title">{t("myCarePartners")}</div>
            <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.5 }}>
              {t("myCarePartnersDesc")}
            </div>
          </div>

          {carePartners.length === 0 ? (
            <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
              <div className="muted-text">{t("noCarePartnersDesc")}</div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {carePartners.map((cp) => (
                <div
                  key={cp.care_partner_user_id}
                  className="soft-card-tight"
                  style={{ padding: 18 }}
                >
                  <div style={{ fontWeight: 900, fontSize: 16 }}>{cp.care_partner_name}</div>
                  <div className="muted-text" style={{ marginTop: 4 }}>{cp.care_partner_email}</div>
                  <div className="muted-text" style={{ marginTop: 6, fontSize: 12 }}>
                    {t("linkedAt")} {formatDate(cp.linked_at)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Pending Doctor Requests */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 16,
              marginBottom: 18,
              flexWrap: "wrap",
            }}
          >
            <div>
              <div className="section-title">{t("pendingRequests")}</div>
              <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.5 }}>
                {t("doctorAccessRequests")}
              </div>
            </div>

            {pendingRequests.length > 0 && (
              <span
                style={{
                  display: "inline-flex",
                  padding: "6px 12px",
                  borderRadius: 999,
                  background: "var(--warn-bg)",
                  color: "var(--warn-text)",
                  fontWeight: 950,
                  fontSize: 13,
                }}
              >
                {pendingRequests.length}
              </span>
            )}
          </div>

          {pendingRequests.length === 0 ? (
            <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
              <div className="muted-text">{t("noPendingRequestsDesc")}</div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {pendingRequests.map((request) => (
                <div
                  key={request.id}
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    background:
                      "linear-gradient(135deg, color-mix(in srgb, var(--warn-bg) 40%, var(--panel)), var(--panel))",
                    borderColor: "var(--warn-border)",
                  }}
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(0,1fr) auto",
                      gap: 16,
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 900, fontSize: 16 }}>
                        {valueOrDash(request.doctor_name)}
                      </div>
                      <div className="muted-text" style={{ marginTop: 4 }}>
                        {valueOrDash(request.doctor_email)}
                      </div>
                      <div className="muted-text" style={{ marginTop: 6 }}>
                        {valueOrDash(request.doctor_department)} · {valueOrDash(request.doctor_hospital_name)}
                      </div>
                      <div className="muted-text" style={{ marginTop: 6, fontSize: 12 }}>
                        {t("requestedAt")} {formatDate(request.requested_at)}
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      <button
                        className="primary-btn"
                        onClick={() => respondToRequest(request.id, "approved")}
                        disabled={respondingId === request.id}
                      >
                        {respondingId === request.id ? t("working") : t("approve")}
                      </button>
                      <button
                        className="secondary-btn"
                        onClick={() => respondToRequest(request.id, "denied")}
                        disabled={respondingId === request.id}
                      >
                        {t("deny")}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Active Doctor Access */}
        <div className="soft-card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 18 }}>
            <div className="section-title">{t("activeAccess")}</div>
            <div className="muted-text" style={{ marginTop: 5, lineHeight: 1.5 }}>
              {t("myDoctors")}
            </div>
          </div>

          {doctorAccess.length === 0 ? (
            <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
              <div className="muted-text">{t("noActiveAccessDesc")}</div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {doctorAccess.map((doctor) => (
                <div
                  key={doctor.doctor_user_id}
                  className="soft-card-tight"
                  style={{
                    padding: 18,
                    display: "grid",
                    gridTemplateColumns: "minmax(0,1fr) auto",
                    gap: 16,
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 900, fontSize: 16 }}>{doctor.doctor_name}</div>
                    <div className="muted-text" style={{ marginTop: 4 }}>{doctor.doctor_email}</div>
                    <div className="muted-text" style={{ marginTop: 6 }}>
                      {valueOrDash(doctor.department)} · {valueOrDash(doctor.hospital_name)}
                    </div>
                    <div className="muted-text" style={{ marginTop: 6, fontSize: 12 }}>
                      {t("grantedAt")} {formatDate(doctor.granted_at)}
                    </div>
                  </div>

                  <button
                    onClick={() => setRevokeTarget(doctor)}
                    style={{
                      border: "1px solid var(--danger-border)",
                      background: "var(--danger-bg)",
                      color: "var(--danger-text)",
                      borderRadius: 14,
                      padding: "10px 14px",
                      fontWeight: 950,
                      fontSize: 13,
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t("revokeAccess")}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
