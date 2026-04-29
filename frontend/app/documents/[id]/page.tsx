"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
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

type UploadedBy = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type LabRow = {
  id: number;
  raw_test_name?: string | null;
  canonical_name?: string | null;
  display_name?: string | null;
  category?: string | null;
  value?: string | null;
  flag?: string | null;
  reference_range?: string | null;
  unit?: string | null;
  is_abnormal?: boolean;
};

type AuditLog = {
  action: string;
  actor?: string | null;
  timestamp: string;
  details?: string | null;
};

type LinkedDocument = {
  id: number;
  filename: string;
  report_name?: string | null;
  report_type?: string | null;
  section: string;
  test_date?: string | null;
  collected_on?: string | null;
  is_verified?: boolean;
  is_linked?: boolean;
};

type DocumentResponse = {
  document_id: number;
  patient_id: number;
  filename: string;
  content_type?: string | null;
  saved_to?: string | null;
  section: string;
  uploaded_by_user_id?: number | null;
  uploaded_by?: UploadedBy | null;
  can_edit_note?: boolean;
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
    note_body?: string | null;
    is_verified?: boolean;
    verified_by?: string | null;
    verified_at?: string | null;
    last_edited_at?: string | null;
    created_at?: string | null;
    labs: LabRow[];
    audit_logs: AuditLog[];
    linked_documents?: LinkedDocument[];
    available_linkable_documents?: LinkedDocument[];
  };
};

type EditableLabRow = {
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

const CATEGORY_ORDER = [
  "Hematologie",
  "Coagulare",
  "Biochimie generala",
  "Endocrinologie",
  "Imunologie",
  "Markeri tumorali",
  "Biologie moleculara generala",
  "Microbiologie",
  "Alte analize",
];

const CATEGORY_OPTIONS = CATEGORY_ORDER;

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes bloodworkSpin {
          to {
            transform: rotate(360deg);
          }
        }

        .bloodwork-spinner {
          width: ${size}px;
          height: ${size}px;
          border-radius: 999px;
          border: 2px solid var(--border);
          border-top-color: var(--primary);
          animation: bloodworkSpin 0.8s linear infinite;
        }
      `}</style>
      <span className="bloodwork-spinner" />
    </>
  );
}

function isAbnormalFlag(flag?: string | null) {
  const cleaned = (flag || "").trim().toLowerCase();
  return ["high", "low", "abnormal", "critical", "borderline"].includes(cleaned);
}

function formatDate(value?: string | null) {
  if (!value) return "—";

  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;

  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function bestDisplayName(lab: LabRow | EditableLabRow) {
  return lab.display_name || lab.canonical_name || lab.raw_test_name || "Unnamed test";
}

function getFlagStyle(flag?: string | null) {
  const abnormal = isAbnormalFlag(flag);

  if (!flag || flag === "Normal") {
    return {
      background: "var(--success-bg)",
      color: "var(--success-text)",
      borderColor: "var(--success-border)",
    };
  }

  if (abnormal) {
    return {
      background: "var(--danger-bg)",
      color: "var(--danger-text)",
      borderColor: "var(--danger-border)",
    };
  }

  return {
    background: "var(--panel-2)",
    color: "var(--muted)",
    borderColor: "var(--border)",
  };
}

function categorySortIndex(category: string) {
  const index = CATEGORY_ORDER.indexOf(category);
  return index === -1 ? 999 : index;
}

export default function DocumentStructuredPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const documentId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documentData, setDocumentData] = useState<DocumentResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [openingOriginal, setOpeningOriginal] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [error, setError] = useState("");

  const [editMode, setEditMode] = useState(false);
  const [noteEditMode, setNoteEditMode] = useState(false);

  const [patientName, setPatientName] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState("");
  const [cnp, setCnp] = useState("");
  const [patientIdentifier, setPatientIdentifier] = useState("");

  const [labName, setLabName] = useState("");
  const [sampleType, setSampleType] = useState("");
  const [referringDoctor, setReferringDoctor] = useState("");
  const [reportName, setReportName] = useState("");
  const [reportType, setReportType] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("");
  const [testDate, setTestDate] = useState("");
  const [collectedOn, setCollectedOn] = useState("");
  const [reportedOn, setReportedOn] = useState("");
  const [registeredOn, setRegisteredOn] = useState("");
  const [generatedOn, setGeneratedOn] = useState("");
  const [labs, setLabs] = useState<EditableLabRow[]>([]);

  const [noteTitle, setNoteTitle] = useState("");
  const [noteBody, setNoteBody] = useState("");

  async function fetchData() {
    const [meResponse, documentResponse] = await Promise.all([
      api.get<CurrentUser>("/auth/me"),
      api.get<DocumentResponse>(`/documents/${documentId}`),
    ]);

    setCurrentUser(meResponse.data);
    setDocumentData(documentResponse.data);
    hydrateForm(documentResponse.data);
  }

  function hydrateForm(next: DocumentResponse) {
    const parsed = next.parsed_data;

    setPatientName(parsed.patient_name || "");
    setDateOfBirth(parsed.date_of_birth || "");
    setAge(parsed.age || "");
    setSex(parsed.sex || "");
    setCnp(parsed.cnp || "");
    setPatientIdentifier(parsed.patient_identifier || "");

    setLabName(parsed.lab_name || "");
    setSampleType(parsed.sample_type || "");
    setReferringDoctor(parsed.referring_doctor || "");
    setReportName(parsed.report_name || "");
    setReportType(parsed.report_type || "");
    setSourceLanguage(parsed.source_language || "");
    setTestDate(parsed.test_date || "");
    setCollectedOn(parsed.collected_on || "");
    setReportedOn(parsed.reported_on || "");
    setRegisteredOn(parsed.registered_on || "");
    setGeneratedOn(parsed.generated_on || "");

    setLabs(
      (parsed.labs || []).map((lab) => ({
        id: lab.id,
        raw_test_name: lab.raw_test_name || "",
        canonical_name: lab.canonical_name || "",
        display_name: lab.display_name || "",
        category: lab.category || "Alte analize",
        value: lab.value || "",
        flag: lab.flag || "",
        reference_range: lab.reference_range || "",
        unit: lab.unit || "",
      }))
    );

    setNoteTitle(parsed.report_name || "");
    setNoteBody(parsed.note_body || "");
  }

  useEffect(() => {
    async function init() {
      try {
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, "Could not load document."));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const isNote = documentData?.section === "notes";
  const canEditStructured = currentUser?.role === "doctor" || currentUser?.role === "admin";
  const canVerify = currentUser?.role === "doctor" || currentUser?.role === "admin";
  const canEditNote = Boolean(documentData?.can_edit_note);
  const canDelete =
    Boolean(currentUser && documentData && currentUser.id === documentData.uploaded_by_user_id) ||
    currentUser?.role === "admin";

  const abnormalLabs = useMemo(() => {
    return (documentData?.parsed_data.labs || []).filter((lab) => lab.is_abnormal || isAbnormalFlag(lab.flag));
  }, [documentData]);

  const orderedGroupedLabs = useMemo(() => {
    const groups = new Map<string, LabRow[]>();

    for (const lab of documentData?.parsed_data.labs || []) {
      const key = lab.category || "Alte analize";

      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)?.push(lab);
    }

    return Array.from(groups.entries())
      .sort(([a], [b]) => categorySortIndex(a) - categorySortIndex(b))
      .map(([category, rows]) => ({ category, rows }));
  }, [documentData]);

  async function openOriginal() {
    if (!documentData) return;

    try {
      setOpeningOriginal(true);
      setError("");

      const response = await api.get(`/documents/${documentData.document_id}/file`, {
        responseType: "blob",
      });

      const rawContentType = response.headers["content-type"];
      const contentType =
        typeof rawContentType === "string" ? rawContentType : documentData.content_type || "application/octet-stream";

      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);

      window.open(fileUrl, "_blank", "noopener,noreferrer");

      setTimeout(() => {
        window.URL.revokeObjectURL(fileUrl);
      }, 60_000);
    } catch (err) {
      setError(
        getErrorMessage(
          err,
          "Could not open original file. If this is an older upload, re-upload it after the persistent disk fix."
        )
      );
    } finally {
      setOpeningOriginal(false);
    }
  }

  async function verifyDocument() {
    if (!documentData) return;

    try {
      setVerifying(true);
      setError("");

      const response = await api.post<DocumentResponse>(`/documents/${documentData.document_id}/verify`, {
        verifier_name: currentUser?.full_name || "Reviewer",
      });

      setDocumentData(response.data);
      hydrateForm(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not verify document."));
    } finally {
      setVerifying(false);
    }
  }

  async function deleteDocument() {
    if (!documentData) return;

    try {
      setDeleting(true);
      setError("");

      await api.delete(`/documents/${documentData.document_id}`);

      if (documentData.patient_id) {
        router.push(`/patients/${documentData.patient_id}`);
      } else {
        router.push("/my-records");
      }
    } catch (err) {
      setError(getErrorMessage(err, "Could not delete document."));
      setConfirmDeleteOpen(false);
    } finally {
      setDeleting(false);
    }
  }

  function updateLab(index: number, key: keyof EditableLabRow, value: string) {
    setLabs((prev) => prev.map((lab, currentIndex) => (currentIndex === index ? { ...lab, [key]: value } : lab)));
  }

  function addLabRow() {
    setLabs((prev) => [
      ...prev,
      {
        raw_test_name: "",
        canonical_name: "",
        display_name: "",
        category: "Alte analize",
        value: "",
        flag: "Normal",
        reference_range: "",
        unit: "",
      },
    ]);
  }

  function removeLabRow(index: number) {
    setLabs((prev) => prev.filter((_, currentIndex) => currentIndex !== index));
  }

  async function saveStructuredData(event: FormEvent) {
    event.preventDefault();

    if (!documentData) return;

    try {
      setSaving(true);
      setError("");

      const response = await api.put<DocumentResponse>(`/documents/${documentData.document_id}`, {
        editor_name: currentUser?.full_name || "Manual User",
        parsed_data: {
          patient_name: patientName || null,
          date_of_birth: dateOfBirth || null,
          age: age || null,
          sex: sex || null,
          cnp: cnp || null,
          patient_identifier: patientIdentifier || null,
          lab_name: labName || null,
          sample_type: sampleType || null,
          referring_doctor: referringDoctor || null,
          report_name: reportName || null,
          report_type: reportType || null,
          source_language: sourceLanguage || null,
          test_date: testDate || null,
          collected_on: collectedOn || null,
          reported_on: reportedOn || null,
          registered_on: registeredOn || null,
          generated_on: generatedOn || null,
          labs: labs.map((lab) => ({
            raw_test_name: lab.raw_test_name || lab.display_name || lab.canonical_name || null,
            canonical_name: lab.canonical_name || lab.display_name || lab.raw_test_name || null,
            display_name: lab.display_name || lab.canonical_name || lab.raw_test_name || null,
            category: lab.category || "Alte analize",
            value: lab.value || null,
            flag: lab.flag || null,
            reference_range: lab.reference_range || null,
            unit: lab.unit || null,
          })),
        },
      });

      setDocumentData(response.data);
      hydrateForm(response.data);
      setEditMode(false);
    } catch (err) {
      setError(getErrorMessage(err, "Could not save structured data."));
    } finally {
      setSaving(false);
    }
  }

  async function saveNote(event: FormEvent) {
    event.preventDefault();

    if (!documentData) return;

    if (!noteBody.trim()) {
      setError("Note body is required.");
      return;
    }

    try {
      setSavingNote(true);
      setError("");

      const response = await api.put<DocumentResponse>(`/documents/${documentData.document_id}/note`, {
        title: noteTitle || documentData.parsed_data.report_name || "Clinical Note",
        content: noteBody,
      });

      setDocumentData(response.data);
      hydrateForm(response.data);
      setNoteEditMode(false);
    } catch (err) {
      setError(getErrorMessage(err, "Could not save note."));
    } finally {
      setSavingNote(false);
    }
  }

  if (loading || !currentUser || !documentData) {
    return (
      <main
        className="app-page-bg"
        style={{
          minHeight: "100vh",
          padding: 24,
          display: "grid",
          placeItems: "center",
        }}
      >
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">Loading structured document...</span>
        </div>
      </main>
    );
  }

  const parsed = documentData.parsed_data;

  return (
    <AppShell
      user={currentUser}
      title={parsed.report_name || documentData.filename || "Document"}
      subtitle={`${valueOrDash(parsed.patient_name)} · ${valueOrDash(parsed.report_type)} · ${
        parsed.is_verified ? "Verified" : "Unverified"
      }`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.back()}>
          Back
        </button>
      }
    >
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

      {confirmDeleteOpen && (
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
            style={{
              width: "min(520px, 100%)",
              padding: 24,
              boxShadow: "0 30px 90px rgba(15, 23, 42, 0.32)",
            }}
          >
            <div style={{ fontSize: 24, fontWeight: 950, letterSpacing: "-0.05em" }}>Delete this report?</div>

            <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.65 }}>
              This removes the report from the patient files and timeline. This can only be done by the uploader or an
              admin.
            </div>

            <div
              className="soft-card-tight"
              style={{
                marginTop: 16,
                padding: 14,
                background: "var(--panel-2)",
              }}
            >
              <div style={{ fontWeight: 900 }}>{parsed.report_name || documentData.filename}</div>
              <div className="muted-text" style={{ marginTop: 5 }}>
                Uploaded by {valueOrDash(documentData.uploaded_by?.full_name)}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
              <button className="secondary-btn" onClick={() => setConfirmDeleteOpen(false)} disabled={deleting}>
                Cancel
              </button>
              <button
                onClick={deleteDocument}
                disabled={deleting}
                style={{
                  border: "1px solid var(--danger-border)",
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  borderRadius: 14,
                  padding: "11px 15px",
                  fontWeight: 950,
                  cursor: deleting ? "not-allowed" : "pointer",
                }}
              >
                {deleting ? "Deleting..." : "Delete report"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div
        className="soft-card"
        style={{
          padding: 22,
          marginBottom: 24,
          background: "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--panel)), var(--panel))",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <span
                style={{
                  display: "inline-flex",
                  padding: "7px 11px",
                  borderRadius: 999,
                  background: parsed.is_verified ? "var(--success-bg)" : "var(--warn-bg)",
                  color: parsed.is_verified ? "var(--success-text)" : "var(--warn-text)",
                  border: `1px solid ${parsed.is_verified ? "var(--success-border)" : "var(--warn-border)"}`,
                  fontWeight: 900,
                  fontSize: 12,
                }}
              >
                {parsed.is_verified ? "Verified" : "Unverified"}
              </span>

              <span
                style={{
                  display: "inline-flex",
                  padding: "7px 11px",
                  borderRadius: 999,
                  background: "var(--panel-2)",
                  color: "var(--muted)",
                  border: "1px solid var(--border)",
                  fontWeight: 900,
                  fontSize: 12,
                }}
              >
                {documentData.section}
              </span>

              {!isNote && abnormalLabs.length > 0 && (
                <span
                  style={{
                    display: "inline-flex",
                    padding: "7px 11px",
                    borderRadius: 999,
                    background: "var(--danger-bg)",
                    color: "var(--danger-text)",
                    border: "1px solid var(--danger-border)",
                    fontWeight: 900,
                    fontSize: 12,
                  }}
                >
                  {abnormalLabs.length} abnormal
                </span>
              )}
            </div>

            <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.6 }}>
              Uploaded by {valueOrDash(documentData.uploaded_by?.full_name)} · Created {formatDate(parsed.created_at)}
              {parsed.last_edited_at ? ` · Edited ${formatDate(parsed.last_edited_at)}` : ""}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {!isNote && (
              <button className="secondary-btn" onClick={openOriginal} disabled={openingOriginal}>
                {openingOriginal ? "Opening..." : "Open original"}
              </button>
            )}

            {canVerify && !parsed.is_verified && (
              <button className="primary-btn" onClick={verifyDocument} disabled={verifying}>
                {verifying ? "Verifying..." : "Verify"}
              </button>
            )}

            {!isNote && canEditStructured && (
              <button className={editMode ? "secondary-btn" : "primary-btn"} onClick={() => setEditMode((prev) => !prev)}>
                {editMode ? "Cancel edit" : "Edit structured data"}
              </button>
            )}

            {isNote && canEditNote && (
              <button className={noteEditMode ? "secondary-btn" : "primary-btn"} onClick={() => setNoteEditMode((prev) => !prev)}>
                {noteEditMode ? "Cancel edit" : "Edit note"}
              </button>
            )}

            {canDelete && (
              <button
                onClick={() => setConfirmDeleteOpen(true)}
                style={{
                  border: "1px solid var(--danger-border)",
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  borderRadius: 14,
                  padding: "11px 15px",
                  fontWeight: 950,
                  cursor: "pointer",
                }}
              >
                Delete
              </button>
            )}
          </div>
        </div>
      </div>

      {isNote ? (
        <div className="soft-card" style={{ padding: 24 }}>
          {!noteEditMode ? (
            <>
              <div className="section-title" style={{ marginBottom: 14 }}>
                {parsed.report_name || "Clinical Note"}
              </div>

              <div
                className="soft-card-tight"
                style={{
                  padding: 20,
                  background: "var(--panel)",
                  lineHeight: 1.8,
                  whiteSpace: "pre-wrap",
                }}
              >
                {parsed.note_body || "No note body."}
              </div>
            </>
          ) : (
            <form onSubmit={saveNote} style={{ display: "grid", gap: 14 }}>
              <input
                className="text-input"
                value={noteTitle}
                onChange={(e) => setNoteTitle(e.target.value)}
                placeholder="Note title"
                disabled={savingNote}
              />

              <textarea
                className="text-input"
                value={noteBody}
                onChange={(e) => setNoteBody(e.target.value)}
                rows={16}
                placeholder="Write clinical note..."
                disabled={savingNote}
                style={{ resize: "vertical", lineHeight: 1.7 }}
              />

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button type="button" className="secondary-btn" onClick={() => setNoteEditMode(false)} disabled={savingNote}>
                  Cancel
                </button>
                <button type="submit" className="primary-btn" disabled={savingNote}>
                  {savingNote ? "Saving..." : "Save note"}
                </button>
              </div>
            </form>
          )}
        </div>
      ) : editMode ? (
        <form onSubmit={saveStructuredData} style={{ display: "grid", gap: 24 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 20,
            }}
          >
            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 16 }}>
                Patient
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                <input className="text-input" value={patientName} onChange={(e) => setPatientName(e.target.value)} placeholder="Patient name" />
                <input className="text-input" value={dateOfBirth} onChange={(e) => setDateOfBirth(e.target.value)} placeholder="Date of birth" />
                <input className="text-input" value={age} onChange={(e) => setAge(e.target.value)} placeholder="Age" />
                <input className="text-input" value={sex} onChange={(e) => setSex(e.target.value)} placeholder="Sex" />
                <input className="text-input" value={cnp} onChange={(e) => setCnp(e.target.value)} placeholder="CNP" />
                <input
                  className="text-input"
                  value={patientIdentifier}
                  onChange={(e) => setPatientIdentifier(e.target.value)}
                  placeholder="Patient ID"
                />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 16 }}>
                Document details
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                <input className="text-input" value={reportName} onChange={(e) => setReportName(e.target.value)} placeholder="Report name" />
                <input className="text-input" value={reportType} onChange={(e) => setReportType(e.target.value)} placeholder="Report type" />
                <input className="text-input" value={labName} onChange={(e) => setLabName(e.target.value)} placeholder="Lab" />
                <input className="text-input" value={sampleType} onChange={(e) => setSampleType(e.target.value)} placeholder="Sample type" />
                <input
                  className="text-input"
                  value={referringDoctor}
                  onChange={(e) => setReferringDoctor(e.target.value)}
                  placeholder="Referring doctor"
                />
                <input
                  className="text-input"
                  value={sourceLanguage}
                  onChange={(e) => setSourceLanguage(e.target.value)}
                  placeholder="Source language"
                />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 16 }}>
                Dates
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                <input className="text-input" value={testDate} onChange={(e) => setTestDate(e.target.value)} placeholder="Test date" />
                <input className="text-input" value={collectedOn} onChange={(e) => setCollectedOn(e.target.value)} placeholder="Collected on" />
                <input className="text-input" value={reportedOn} onChange={(e) => setReportedOn(e.target.value)} placeholder="Reported on" />
                <input className="text-input" value={registeredOn} onChange={(e) => setRegisteredOn(e.target.value)} placeholder="Registered on" />
                <input className="text-input" value={generatedOn} onChange={(e) => setGeneratedOn(e.target.value)} placeholder="Generated on" />
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 16 }}>
              <div>
                <div className="section-title">Structured lab rows</div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  Edit categories, values, units, references, and flags.
                </div>
              </div>

              <button type="button" className="secondary-btn" onClick={addLabRow}>
                Add row
              </button>
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              {labs.map((lab, index) => (
                <div
                  key={`${lab.id || "new"}-${index}`}
                  className="soft-card-tight"
                  style={{
                    padding: 14,
                    display: "grid",
                    gridTemplateColumns: "1.1fr 1fr 0.8fr 0.7fr 1fr 0.8fr auto",
                    gap: 10,
                    alignItems: "center",
                  }}
                >
                  <input
                    className="text-input"
                    value={lab.display_name || lab.raw_test_name || ""}
                    onChange={(e) => {
                      updateLab(index, "display_name", e.target.value);
                      updateLab(index, "raw_test_name", e.target.value);
                    }}
                    placeholder="Test"
                  />

                  <select
                    className="text-input"
                    value={lab.category || "Alte analize"}
                    onChange={(e) => updateLab(index, "category", e.target.value)}
                  >
                    {CATEGORY_OPTIONS.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
                  </select>

                  <input className="text-input" value={lab.value || ""} onChange={(e) => updateLab(index, "value", e.target.value)} placeholder="Value" />
                  <input className="text-input" value={lab.unit || ""} onChange={(e) => updateLab(index, "unit", e.target.value)} placeholder="Unit" />
                  <input
                    className="text-input"
                    value={lab.reference_range || ""}
                    onChange={(e) => updateLab(index, "reference_range", e.target.value)}
                    placeholder="Reference"
                  />
                  <select className="text-input" value={lab.flag || ""} onChange={(e) => updateLab(index, "flag", e.target.value)}>
                    <option value="">—</option>
                    <option value="Normal">Normal</option>
                    <option value="High">High</option>
                    <option value="Low">Low</option>
                    <option value="Abnormal">Abnormal</option>
                    <option value="Critical">Critical</option>
                    <option value="Borderline">Borderline</option>
                  </select>
                  <button type="button" className="secondary-btn" onClick={() => removeLabRow(index)}>
                    ×
                  </button>
                </div>
              ))}

              {!labs.length && (
                <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                  No lab rows yet.
                </div>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 }}>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => {
                  hydrateForm(documentData);
                  setEditMode(false);
                }}
                disabled={saving}
              >
                Cancel
              </button>
              <button type="submit" className="primary-btn" disabled={saving}>
                {saving ? "Saving..." : "Save structured data"}
              </button>
            </div>
          </div>
        </form>
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 20,
              marginBottom: 24,
            }}
          >
            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 14 }}>
                Patient
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                {[
                  ["Name", parsed.patient_name],
                  ["Date of birth", parsed.date_of_birth],
                  ["Age", parsed.age],
                  ["Sex", parsed.sex],
                  ["CNP", parsed.cnp],
                  ["Patient ID", parsed.patient_identifier],
                ].map(([label, value]) => (
                  <div key={label} className="soft-card-tight" style={{ padding: 14, background: "var(--panel)" }}>
                    <div className="muted-text" style={{ fontSize: 12, fontWeight: 800 }}>
                      {label}
                    </div>
                    <div style={{ marginTop: 5, fontWeight: 900 }}>{valueOrDash(value)}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 14 }}>
                Document details
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                {[
                  ["Report name", parsed.report_name],
                  ["Report type", parsed.report_type],
                  ["Lab", parsed.lab_name],
                  ["Sample type", parsed.sample_type],
                  ["Referring doctor", parsed.referring_doctor],
                  ["Source language", parsed.source_language],
                ].map(([label, value]) => (
                  <div key={label} className="soft-card-tight" style={{ padding: 14, background: "var(--panel)" }}>
                    <div className="muted-text" style={{ fontSize: 12, fontWeight: 800 }}>
                      {label}
                    </div>
                    <div style={{ marginTop: 5, fontWeight: 900 }}>{valueOrDash(value)}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 14 }}>
                Dates
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                {[
                  ["Test date", parsed.test_date],
                  ["Collected on", parsed.collected_on],
                  ["Reported on", parsed.reported_on],
                  ["Registered on", parsed.registered_on],
                  ["Generated on", parsed.generated_on],
                ].map(([label, value]) => (
                  <div key={label} className="soft-card-tight" style={{ padding: 14, background: "var(--panel)" }}>
                    <div className="muted-text" style={{ fontSize: 12, fontWeight: 800 }}>
                      {label}
                    </div>
                    <div style={{ marginTop: 5, fontWeight: 900 }}>{valueOrDash(value)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {abnormalLabs.length > 0 && (
            <div
              className="soft-card"
              style={{
                padding: 24,
                marginBottom: 24,
                borderColor: "var(--danger-border)",
                background: "linear-gradient(135deg, var(--danger-bg), var(--panel))",
              }}
            >
              <div className="section-title" style={{ marginBottom: 12 }}>
                Abnormal results
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {abnormalLabs.map((lab, index) => (
                  <span
                    key={`abnormal-${lab.id}-${lab.canonical_name || lab.display_name || lab.raw_test_name}-${index}`}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "8px 11px",
                      borderRadius: 999,
                      background: "var(--panel)",
                      color: "var(--danger-text)",
                      border: "1px solid var(--danger-border)",
                      fontWeight: 850,
                      fontSize: 13,
                    }}
                  >
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 999,
                        background: "var(--danger-text)",
                      }}
                    />
                    {bestDisplayName(lab)} · {valueOrDash(lab.value)} {valueOrDash(lab.unit)}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>
              Structured Data
            </div>

            <div className="muted-text" style={{ marginBottom: 18 }}>
              {(parsed.labs || []).length} structured lab rows extracted.
            </div>

            {orderedGroupedLabs.length > 0 ? (
              <div style={{ display: "grid", gap: 26 }}>
                {orderedGroupedLabs.map(({ category, rows }) => (
                  <section key={category}>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 950,
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        color: "var(--muted)",
                        marginBottom: 10,
                      }}
                    >
                      {category}
                    </div>

                    <div
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: 20,
                        overflow: "hidden",
                        background: "var(--panel)",
                      }}
                    >
                      <table style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                          <tr style={{ background: "var(--panel-2)" }}>
                            {["Test", "Value", "Unit", "Reference range", "Flag"].map((header) => (
                              <th
                                key={header}
                                style={{
                                  padding: 14,
                                  textAlign: header === "Test" ? "left" : "center",
                                  fontSize: 12,
                                  color: "var(--muted)",
                                  fontWeight: 950,
                                  borderBottom: "1px solid var(--border)",
                                }}
                              >
                                {header}
                              </th>
                            ))}
                          </tr>
                        </thead>

                        <tbody>
                          {rows.map((lab, index) => {
                            const flagStyle = getFlagStyle(lab.flag);
                            const abnormal = lab.is_abnormal || isAbnormalFlag(lab.flag);

                            return (
                              <tr
                                key={`${category}-${lab.id}-${lab.canonical_name || lab.display_name || lab.raw_test_name}-${index}`}
                                style={{
                                  background: abnormal ? "var(--danger-bg)" : "transparent",
                                  borderBottom: index === rows.length - 1 ? "none" : "1px solid var(--border)",
                                }}
                              >
                                <td style={{ padding: 14, textAlign: "left" }}>
                                  <div style={{ display: "flex", gap: 9, alignItems: "center" }}>
                                    {abnormal && (
                                      <span
                                        style={{
                                          width: 8,
                                          height: 8,
                                          borderRadius: 999,
                                          background: "var(--danger-text)",
                                          flex: "0 0 auto",
                                        }}
                                      />
                                    )}
                                    <div>
                                      <div style={{ fontWeight: 900 }}>{bestDisplayName(lab)}</div>
                                      <div className="muted-text" style={{ fontSize: 12, marginTop: 3 }}>
                                        Raw: {valueOrDash(lab.raw_test_name)}
                                      </div>
                                    </div>
                                  </div>
                                </td>

                                <td style={{ padding: 14, textAlign: "center", fontWeight: 950 }}>{valueOrDash(lab.value)}</td>
                                <td style={{ padding: 14, textAlign: "center" }}>{valueOrDash(lab.unit)}</td>
                                <td style={{ padding: 14, textAlign: "center" }}>{valueOrDash(lab.reference_range)}</td>
                                <td style={{ padding: 14, textAlign: "center" }}>
                                  <span
                                    style={{
                                      display: "inline-flex",
                                      padding: "6px 10px",
                                      borderRadius: 999,
                                      border: `1px solid ${flagStyle.borderColor}`,
                                      background: flagStyle.background,
                                      color: flagStyle.color,
                                      fontSize: 12,
                                      fontWeight: 950,
                                    }}
                                  >
                                    {valueOrDash(lab.flag || "Normal")}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </section>
                ))}
              </div>
            ) : (
              <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                <div style={{ fontWeight: 900 }}>No structured lab values found.</div>
                <div className="muted-text" style={{ marginTop: 6 }}>
                  If this was a lab report, re-upload after the OCR/AI extraction backend is deployed.
                </div>
              </div>
            )}
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 14 }}>
              Audit trail
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              {(parsed.audit_logs || []).map((log, index) => (
                <div key={`${log.action}-${log.timestamp}-${index}`} className="soft-card-tight" style={{ padding: 14 }}>
                  <div style={{ fontWeight: 900 }}>{log.action}</div>
                  <div className="muted-text" style={{ marginTop: 4 }}>
                    {valueOrDash(log.actor)} · {formatDate(log.timestamp)}
                  </div>
                  {log.details && (
                    <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.5 }}>
                      {log.details}
                    </div>
                  )}
                </div>
              ))}

              {!parsed.audit_logs?.length && (
                <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                  No audit logs yet.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}