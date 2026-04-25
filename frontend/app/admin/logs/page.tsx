"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type Log = {
  id: number;
  admin_name: string;
  action: string;
  patient_name?: string | null;
  doctor_name?: string | null;
  timestamp: string;
  details?: string | null;
};

function prettyAction(action: string) {
  return action
    .replaceAll("_", " ")
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function prettyDateTime(value?: string | null) {
  if (!value) return "—";

  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;

  return d.toLocaleString();
}

export default function AdminLogsPage() {
  const router = useRouter();
  const { t } = useLanguage();

  const [logs, setLogs] = useState<Log[]>([]);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadData() {
    const me = await api.get<CurrentUser>("/auth/me");

    if (me.data.role !== "admin") {
      router.push(me.data.role === "doctor" ? "/my-patients" : "/my-records");
      return;
    }

    setUser(me.data);

    const res = await api.get<Log[]>("/admin/action-logs");
    setLogs(res.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await loadData();
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadActivityLog")));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, []);

  const filteredLogs = useMemo(() => {
    const term = query.trim().toLowerCase();

    return logs
      .filter((log) => {
        if (!term) return true;

        return [
          log.admin_name,
          log.action,
          log.patient_name,
          log.doctor_name,
          log.details,
          log.timestamp,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(term);
      })
      .sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
  }, [logs, query]);

  if (loading || !user) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingActivityLog")}</p>
      </main>
    );
  }

  return (
    <AppShell user={user} title={t("activityLog")} subtitle={t("activityLogSubtitle")}>
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

      <div className="soft-card" style={{ padding: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "flex-start",
            marginBottom: 18,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div className="section-title">{t("adminActions")}</div>
            <div className="muted-text" style={{ marginTop: 6 }}>
              {t("adminActionsDesc")}
            </div>
          </div>

          <div
            style={{
              display: "inline-flex",
              padding: "7px 11px",
              borderRadius: 999,
              background: "var(--panel-2)",
              color: "var(--muted)",
              fontWeight: 900,
              fontSize: 12,
              border: "1px solid var(--border)",
            }}
          >
            {filteredLogs.length} {t("records")}
          </div>
        </div>

        <div style={{ marginBottom: 18 }}>
          <input
            className="text-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("search")}
          />
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {filteredLogs.map((log) => (
            <div key={log.id} className="soft-card-tight" style={{ padding: 18 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) auto",
                  gap: 16,
                  alignItems: "start",
                }}
              >
                <div>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ fontWeight: 950, fontSize: 18 }}>
                      {prettyAction(log.action)}
                    </div>

                    <span
                      style={{
                        display: "inline-flex",
                        padding: "5px 10px",
                        borderRadius: 999,
                        background: "var(--panel-2)",
                        color: "var(--muted)",
                        fontWeight: 900,
                        fontSize: 12,
                        border: "1px solid var(--border)",
                      }}
                    >
                      {t("admin")}: {valueOrDash(log.admin_name)}
                    </span>
                  </div>

                  <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.7 }}>
                    {log.patient_name ? `${t("patientLabel")}: ${log.patient_name} · ` : ""}
                    {log.doctor_name ? `${t("doctorLabel")}: ${log.doctor_name} · ` : ""}
                    {t("timestamp")}: {prettyDateTime(log.timestamp)}
                  </div>

                  {log.details && (
                    <div
                      style={{
                        marginTop: 12,
                        padding: 12,
                        borderRadius: 16,
                        background: "var(--panel-2)",
                        border: "1px solid var(--border)",
                        lineHeight: 1.6,
                      }}
                    >
                      <div className="muted-text" style={{ fontSize: 12, fontWeight: 900, marginBottom: 4 }}>
                        {t("details")}
                      </div>
                      {log.details}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}

          {!filteredLogs.length && (
            <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>{t("noActivityLogs")}</div>
              <div className="muted-text" style={{ marginTop: 8 }}>
                {t("noActivityLogsDesc")}
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}