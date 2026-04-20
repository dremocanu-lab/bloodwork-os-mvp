"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type LabResult = {
  id?: number;
  raw_test_name?: string | null;
  canonical_name?: string | null;
  display_name?: string | null;
  category?: string | null;
  value?: string | null;
  flag?: string | null;
  reference_range?: string | null;
  unit?: string | null;
};

type AuditLog = {
  action: string;
  actor?: string | null;
  timestamp: string;
  details?: string | null;
};

type DocumentDetail = {
  document_id: number;
  patient_id: number;
  filename: string;
  content_type?: string | null;
  saved_to: string;
  section: string;
  uploaded_by_user_id?: number | null;
  uploaded_by?: {
    id: number;
    email: string;
    full_name: string;
    role: "patient" | "doctor" | "admin";
    department?: string | null;
    hospital_name?: string | null;
  } | null;
  extracted_text?: string | null;
  parsed_data: {
    patient_name?: string | null;
    date_of_birth?: string | null;
    age?: string | null;
    sex?: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
    lab_name?: string | null;
    sample_type?: string | null;
    referring_doctor?: string | null;
    report_name?: string | null;
    report_type?: string | null;
    source_language?: string | null;
    test_date?: string | null;
    collected_on?: string | null;
    reported_on?: string | null;
    registered_on?: string | null;
    generated_on?: string | null;
    is_verified: boolean;
    verified_by?: string | null;
    verified_at?: string | null;
    last_edited_at?: string | null;
    labs: LabResult[];
    audit_logs: AuditLog[];
  };
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documentData, setDocumentData] = useState<DocumentDetail | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchMe = async () => {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  };

  const fetchDocument = async () => {
    try {
      const response = await api.get<DocumentDetail>(`/documents/${documentId}`);
      setDocumentData(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load structured document data."));
    }
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;
      await fetchDocument();
      setLoading(false);
    };
    init();
  }, [documentId]);

  const openOriginal = () => {
    window.open(`${API_URL}/documents/${documentId}/file`, "_blank");
  };

  const verifyDocument = async () => {
    try {
      setVerifying(true);
      setError("");
      await api.post(`/documents/${documentId}/verify`, {
        verifier_name: currentUser?.full_name || "Reviewer",
      });
      await fetchDocument();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to verify document."));
    } finally {
      setVerifying(false);
    }
  };

  if (loading || !currentUser || !documentData) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading structured document view...</p>
      </main>
    );
  }

  const parsed = documentData.parsed_data;
  const canVerify =
    (currentUser.role === "doctor" || currentUser.role === "admin") && !parsed.is_verified;

  return (
    <AppShell
      user={currentUser}
      title={valueOrDash(parsed.report_name || documentData.filename)}
      subtitle={`${valueOrDash(parsed.report_type)} · ${valueOrDash(parsed.test_date)}`}
      rightContent={
        <div style={{ display: "flex", gap: 10 }}>
          <button className="secondary-btn" onClick={() => router.back()}>
            Back
          </button>
          <button className="secondary-btn" onClick={openOriginal}>
            Open File
          </button>
          {canVerify && (
            <button className="primary-btn" onClick={verifyDocument} disabled={verifying}>
              {verifying ? "Verifying..." : "Verify"}
            </button>
          )}
        </div>
      }
    >
      {error && (
        <div
          className="soft-card-tight"
          style={{
            marginBottom: 20,
            padding: 16,
            borderColor: "#fecaca",
            background: "#fef2f2",
            color: "#b91c1c",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ marginBottom: 20 }}>
        <span
          style={{
            display: "inline-flex",
            padding: "6px 12px",
            borderRadius: 999,
            background: parsed.is_verified ? "#ecfdf5" : "#fff7ed",
            color: parsed.is_verified ? "#047857" : "#c2410c",
            fontSize: 12,
            fontWeight: 800,
          }}
        >
          {parsed.is_verified ? "Verified" : "Unverified"}
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 20,
          marginBottom: 24,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Patient / Report Metadata
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 12 }}>
            <div className="muted-text">Patient</div>
            <div>{valueOrDash(parsed.patient_name)}</div>

            <div className="muted-text">DOB</div>
            <div>{valueOrDash(parsed.date_of_birth)}</div>

            <div className="muted-text">Age</div>
            <div>{valueOrDash(parsed.age)}</div>

            <div className="muted-text">Sex</div>
            <div>{valueOrDash(parsed.sex)}</div>

            <div className="muted-text">CNP</div>
            <div>{valueOrDash(parsed.cnp)}</div>

            <div className="muted-text">Patient ID</div>
            <div>{valueOrDash(parsed.patient_identifier)}</div>

            <div className="muted-text">Report Name</div>
            <div>{valueOrDash(parsed.report_name)}</div>

            <div className="muted-text">Report Type</div>
            <div>{valueOrDash(parsed.report_type)}</div>

            <div className="muted-text">Section</div>
            <div>{valueOrDash(documentData.section)}</div>

            <div className="muted-text">Language</div>
            <div>{valueOrDash(parsed.source_language)}</div>
          </div>
        </div>

        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Source / Provenance
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 12 }}>
            <div className="muted-text">Lab / Site</div>
            <div>{valueOrDash(parsed.lab_name)}</div>

            <div className="muted-text">Sample Type</div>
            <div>{valueOrDash(parsed.sample_type)}</div>

            <div className="muted-text">Referring Doctor</div>
            <div>{valueOrDash(parsed.referring_doctor)}</div>

            <div className="muted-text">Uploaded By</div>
            <div>{valueOrDash(documentData.uploaded_by?.full_name)}</div>

            <div className="muted-text">Uploader Dept</div>
            <div>{valueOrDash(documentData.uploaded_by?.department)}</div>

            <div className="muted-text">Uploader Hospital</div>
            <div>{valueOrDash(documentData.uploaded_by?.hospital_name)}</div>

            <div className="muted-text">Test Date</div>
            <div>{valueOrDash(parsed.test_date)}</div>

            <div className="muted-text">Collected</div>
            <div>{valueOrDash(parsed.collected_on)}</div>

            <div className="muted-text">Reported</div>
            <div>{valueOrDash(parsed.reported_on)}</div>

            <div className="muted-text">Generated</div>
            <div>{valueOrDash(parsed.generated_on)}</div>

            <div className="muted-text">Verified By</div>
            <div>{valueOrDash(parsed.verified_by)}</div>
          </div>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
        <div className="section-title" style={{ marginBottom: 16 }}>
          Parsed Lab Results
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {parsed.labs.map((lab, idx) => (
            <div key={`${lab.display_name}-${idx}`} className="soft-card-tight" style={{ padding: 16 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.4fr 1fr 1fr 1fr auto",
                  gap: 12,
                  alignItems: "center",
                }}
              >
                <div>
                  <div style={{ fontWeight: 800 }}>{valueOrDash(lab.display_name || lab.raw_test_name)}</div>
                  <div className="muted-text" style={{ marginTop: 4 }}>
                    {valueOrDash(lab.category)} · {valueOrDash(lab.canonical_name)}
                  </div>
                </div>
                <div>
                  <div className="muted-text" style={{ fontSize: 12 }}>Value</div>
                  <div style={{ fontWeight: 700 }}>{valueOrDash(lab.value)}</div>
                </div>
                <div>
                  <div className="muted-text" style={{ fontSize: 12 }}>Unit</div>
                  <div style={{ fontWeight: 700 }}>{valueOrDash(lab.unit)}</div>
                </div>
                <div>
                  <div className="muted-text" style={{ fontSize: 12 }}>Reference</div>
                  <div style={{ fontWeight: 700 }}>{valueOrDash(lab.reference_range)}</div>
                </div>
                <div>
                  <div
                    style={{
                      display: "inline-flex",
                      padding: "6px 10px",
                      borderRadius: 999,
                      background:
                        lab.flag === "High"
                          ? "#fef2f2"
                          : lab.flag === "Low"
                          ? "#eff6ff"
                          : "#f3f4f6",
                      color:
                        lab.flag === "High"
                          ? "#b91c1c"
                          : lab.flag === "Low"
                          ? "#1d4ed8"
                          : "#374151",
                      fontSize: 12,
                      fontWeight: 800,
                    }}
                  >
                    {valueOrDash(lab.flag)}
                  </div>
                </div>
              </div>
            </div>
          ))}

          {!parsed.labs.length && (
            <div className="muted-text">No structured lab rows were extracted from this file.</div>
          )}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 20,
        }}
      >
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Audit Trail
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {parsed.audit_logs.map((log, idx) => (
              <div key={idx} className="soft-card-tight" style={{ padding: 16 }}>
                <div style={{ fontWeight: 800 }}>{valueOrDash(log.action)}</div>
                <div className="muted-text" style={{ marginTop: 4 }}>
                  {valueOrDash(log.actor)} · {new Date(log.timestamp).toLocaleString()}
                </div>
                {log.details && <div style={{ marginTop: 8 }}>{log.details}</div>}
              </div>
            ))}

            {!parsed.audit_logs.length && (
              <div className="muted-text">No audit entries yet.</div>
            )}
          </div>
        </div>

        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 16 }}>
            Extracted Text
          </div>

          <div
            style={{
              whiteSpace: "pre-wrap",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              fontSize: 13,
              maxHeight: 480,
              overflowY: "auto",
            }}
          >
            {documentData.extracted_text || "No OCR text extracted."}
          </div>
        </div>
      </div>
    </AppShell>
  );
}