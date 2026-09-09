"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import {
  ConfirmDialog,
  EmptyState,
  ErrorNote,
  SectionHead,
  Skeleton,
  Status,
} from "@/components/ui";
import { IconCheck, IconHeart, IconShield } from "@/components/ui/icon";

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
  const [regenerateOpen, setRegenerateOpen] = useState(false);

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
      density="comfortable"
    >
      <div className="b-stack">
        {error ? <ErrorNote onRetry={() => void load()}>{error}</ErrorNote> : null}

        {/* Pending requests come first: they are the only thing here that
            needs a decision, and burying them under the care-partner code
            (as the old order did) made them easy to miss. */}
        {pendingRequests.length > 0 ? (
          <section className="b-surface">
            <SectionHead
              title={t("pendingRequests")}
              count={pendingRequests.length}
              description={t("doctorAccessRequests")}
            />
            <div className="b-list">
              {pendingRequests.map((request) => (
                <div key={request.id} className="b-list-row" style={{ cursor: "default" }}>
                  <span className="b-avatar" aria-hidden="true">
                    {(request.doctor_name || "?").charAt(0).toUpperCase()}
                  </span>
                  <span className="b-list-main">
                    <span className="b-list-title">{valueOrDash(request.doctor_name)}</span>
                    <span className="b-list-sub">
                      {[request.doctor_email, request.doctor_department, request.doctor_hospital_name]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <span className="b-list-sub">
                      {t("requestedAt")} {formatDate(request.requested_at)}
                    </span>
                  </span>
                  <span className="b-list-trail" style={{ flexDirection: "row", gap: "var(--s2)" }}>
                    <button
                      type="button"
                      className="b-btn b-btn-secondary b-btn-sm"
                      onClick={() => respondToRequest(request.id, "denied")}
                      disabled={respondingId === request.id}
                    >
                      {t("deny")}
                    </button>
                    <button
                      type="button"
                      className="b-btn b-btn-primary b-btn-sm"
                      onClick={() => respondToRequest(request.id, "approved")}
                      disabled={respondingId === request.id}
                    >
                      {respondingId === request.id ? <span className="b-spinner" /> : null}
                      {t("approve")}
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {/* Who can see the record right now. */}
        <section className="b-surface">
          <SectionHead
            title={t("activeAccess")}
            count={doctorAccess.length}
            description={t("myDoctors")}
          />
          <div className="b-list">
            {doctorAccess.length ? (
              doctorAccess.map((doctor) => (
                <div key={doctor.doctor_user_id} className="b-list-row" style={{ cursor: "default" }}>
                  <span className="b-avatar" aria-hidden="true">
                    {doctor.doctor_name.charAt(0).toUpperCase()}
                  </span>
                  <span className="b-list-main">
                    <span className="b-list-title">{doctor.doctor_name}</span>
                    <span className="b-list-sub">
                      {[doctor.doctor_email, doctor.department, doctor.hospital_name]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <span className="b-list-sub">
                      {t("grantedAt")} {formatDate(doctor.granted_at)}
                    </span>
                  </span>
                  <span className="b-list-trail" style={{ flexDirection: "row", gap: "var(--s2)" }}>
                    <Status tone="ok">{t("activeAccess")}</Status>
                    <button
                      type="button"
                      className="b-btn b-btn-danger-quiet b-btn-sm"
                      onClick={() => setRevokeTarget(doctor)}
                    >
                      {t("revokeAccess")}
                    </button>
                  </span>
                </div>
              ))
            ) : (
              <EmptyState
                icon={<IconShield size={17} />}
                title={t("noActiveAccessDesc")}
                description="Only you can see this record right now."
              />
            )}
          </div>
        </section>

        {/* Care partners: who they are, then the code that creates more. */}
        <section className="b-surface">
          <SectionHead
            title={t("myCarePartners")}
            count={carePartners.length}
            description={t("myCarePartnersDesc")}
          />
          <div className="b-list">
            {carePartners.length ? (
              carePartners.map((partner) => (
                <div
                  key={partner.care_partner_user_id}
                  className="b-list-row"
                  style={{ cursor: "default" }}
                >
                  <span className="b-avatar" aria-hidden="true">
                    {partner.care_partner_name.charAt(0).toUpperCase()}
                  </span>
                  <span className="b-list-main">
                    <span className="b-list-title">{partner.care_partner_name}</span>
                    <span className="b-list-sub">{partner.care_partner_email}</span>
                  </span>
                  <span className="b-list-trail" style={{ flexDirection: "row", gap: "var(--s2)" }}>
                    <Status tone="ok">{t("activeAccess")}</Status>
                    <span className="b-range">
                      {t("linkedAt")} {formatDate(partner.linked_at)}
                    </span>
                  </span>
                </div>
              ))
            ) : (
              <EmptyState icon={<IconHeart size={17} />} title={t("noCarePartnersDesc")} />
            )}
          </div>

          <div style={{ padding: "var(--s3) var(--s4)", borderTop: "1px solid var(--border)" }}>
            <div className="b-label">{t("carePartnerCode")}</div>
            <p className="b-meta" style={{ margin: "3px 0 var(--s2)", maxWidth: "70ch" }}>
              {t("carePartnerCodeDesc")}
            </p>

            {carePartnerCode ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--s2)",
                  flexWrap: "wrap",
                }}
              >
                <code
                  style={{
                    fontFamily: "ui-monospace, monospace",
                    fontSize: 15,
                    letterSpacing: "0.05em",
                    padding: "7px 11px",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r)",
                    color: "var(--text)",
                  }}
                >
                  {carePartnerCode.code}
                </code>

                <button type="button" className="b-btn b-btn-secondary b-btn-sm" onClick={copyCode}>
                  {codeCopied ? <IconCheck size={12} /> : null}
                  {codeCopied ? t("copied") : t("copyCode")}
                </button>

                <button
                  type="button"
                  className="b-btn b-btn-ghost b-btn-sm"
                  onClick={() => setRegenerateOpen(true)}
                  disabled={regenerating}
                >
                  {regenerating ? <span className="b-spinner" /> : null}
                  {t("regenerateCode")}
                </button>

                <span className="b-range">
                  {t("codeGeneratedAt")} {formatDate(carePartnerCode.created_at)}
                </span>
              </div>
            ) : (
              <Skeleton width={220} height={30} />
            )}
          </div>
        </section>
      </div>

      {/* Revoking clinician access is sensitive, so the dialog names the
          doctor and states exactly what they lose. */}
      <ConfirmDialog
        open={revokeTarget !== null}
        onClose={() => setRevokeTarget(null)}
        onConfirm={confirmRevoke}
        busy={revoking}
        title={t("revokeAccessConfirmTitle")}
        confirmLabel={revoking ? t("revoking") : t("confirmRevoke")}
        consequence={
          revokeTarget ? (
            <>
              <strong style={{ fontWeight: 600 }}>{revokeTarget.doctor_name}</strong> (
              {revokeTarget.doctor_email}) will immediately lose access to your record.{" "}
              {t("revokeAccessConfirmDesc")}
            </>
          ) : null
        }
      />

      {/* Regenerating the code invalidates the old one, which was previously
          one click of an unstyled button away - so it is confirmed too. */}
      <ConfirmDialog
        open={regenerateOpen}
        onClose={() => setRegenerateOpen(false)}
        onConfirm={async () => {
          await regenerateCode();
          setRegenerateOpen(false);
        }}
        busy={regenerating}
        title={t("regenerateCode")}
        confirmLabel={t("regenerateCode")}
        consequence={t("regenerateCodeWarning")}
      />
    </AppShell>
  );
}
