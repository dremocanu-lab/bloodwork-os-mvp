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
    has_abnormal?: boolean;
    reviewed_by_current_doctor?: boolean;
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

type DischargeSection = {
  key: string;
  title: string;
  original_titles?: string[];
  body: string;
  confidence?: number;
};

type DischargeNotePayload = {
  document_type?: string;
  sections?: DischargeSection[];
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

const NIL_VALUES = new Set(["", "-", "--", "---", "—", "–", "n/a", "na", "nil", "null", "none"]);

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

function normalizeNilText(value?: string | number | null) {
  if (value === null || value === undefined) return "";

  return String(value).trim().toLowerCase().replace("−", "-").replace("—", "-").replace("–", "-");
}

function isNilValue(value?: string | number | null) {
  const cleaned = normalizeNilText(value);
  return NIL_VALUES.has(cleaned) || /^-+$/.test(cleaned);
}

function displayLabValue(value?: string | number | null) {
  if (isNilValue(value)) return "nil";
  return String(value);
}

function cleanLabValueForSave(value?: string | null) {
  if (isNilValue(value)) return null;
  return value?.trim() || null;
}

function isAbnormalFlag(flag?: string | null) {
  const cleaned = (flag || "").trim().toLowerCase();

  if (!cleaned || cleaned === "normal" || cleaned === "none" || cleaned === "ok") return false;

  return ["high", "low", "abnormal", "critical", "borderline"].includes(cleaned);
}

function isEffectivelyNormalFlag(flag?: string | null) {
  const cleaned = (flag || "").trim().toLowerCase();
  return cleaned === "normal" || cleaned === "ok";
}

function hasDisplayableFlag(flag?: string | null) {
  const cleaned = (flag || "").trim().toLowerCase();

  if (!cleaned) return false;

  return !["none", "null", "undefined", "-", "—"].includes(cleaned);
}

function formatDate(value?: string | null) {
  if (!value) return "—";

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) return value;

  return parsed.toLocaleString(undefined, {
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

function categorySortIndex(category: string) {
  const index = CATEGORY_ORDER.indexOf(category);
  return index === -1 ? 999 : index;
}

function getFlagStyle(flag?: string | null, value?: string | number | null) {
  if (isNilValue(value)) {
    return {
      background: "var(--panel-2)",
      color: "var(--muted)",
      borderColor: "var(--border)",
    };
  }

  if (!hasDisplayableFlag(flag)) {
    return {
      background: "var(--panel-2)",
      color: "var(--muted)",
      borderColor: "var(--border)",
    };
  }

  if (isEffectivelyNormalFlag(flag)) {
    return {
      background: "var(--success-bg)",
      color: "var(--success-text)",
      borderColor: "var(--success-border)",
    };
  }

  if (isAbnormalFlag(flag)) {
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

function MetaField({
  label,
  value,
}: {
  label: string;
  value?: string | number | null;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--muted)", lineHeight: 1 }}>
        {label}
      </span>
      <span style={{ fontSize: 14, fontWeight: 950, letterSpacing: "-0.02em", lineHeight: 1.3, wordBreak: "break-word" }}>
        {value === null || value === undefined || value === "" ? "—" : String(value)}
      </span>
    </div>
  );
}

function StatusPill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "success" | "warn" | "danger";
}) {
  const styles =
    tone === "success"
      ? {
          background: "var(--success-bg)",
          color: "var(--success-text)",
          borderColor: "var(--success-border)",
        }
      : tone === "warn"
      ? {
          background: "var(--warn-bg)",
          color: "var(--warn-text)",
          borderColor: "var(--warn-border)",
        }
      : tone === "danger"
      ? {
          background: "var(--danger-bg)",
          color: "var(--danger-text)",
          borderColor: "var(--danger-border)",
        }
      : {
          background: "var(--panel-2)",
          color: "var(--muted)",
          borderColor: "var(--border)",
        };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 999,
        padding: "7px 11px",
        border: `1px solid ${styles.borderColor}`,
        background: styles.background,
        color: styles.color,
        fontWeight: 900,
        fontSize: 12,
        lineHeight: 1,
      }}
    >
      {children}
    </span>
  );
}

function SectionHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 16,
        alignItems: "flex-start",
        flexWrap: "wrap",
        marginBottom: 16,
      }}
    >
      <div>
        <div className="section-title">{title}</div>
        {subtitle && (
          <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.55 }}>
            {subtitle}
          </div>
        )}
      </div>
      {right}
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  placeholder,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <label style={{ display: "grid", gap: 8 }}>
      <span className="muted-text" style={{ fontSize: 12, fontWeight: 900 }}>
        {label}
      </span>
      <input
        className="text-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder || label}
        disabled={disabled}
      />
    </label>
  );
}

function parseDischargePayload(noteBody?: string | null): DischargeNotePayload | null {
  if (!noteBody) return null;

  try {
    const parsed = JSON.parse(noteBody);

    if (
      parsed &&
      typeof parsed === "object" &&
      parsed.document_type === "discharge_summary" &&
      Array.isArray(parsed.sections)
    ) {
      return parsed;
    }

    return null;
  } catch {
    return null;
  }
}

export default function DocumentStructuredPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;
  const { t } = useLanguage();

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
        value: isNilValue(lab.value) ? "" : lab.value || "",
        flag: lab.flag || "",
        reference_range: lab.reference_range || "",
        unit: lab.unit || "",
      }))
    );

    setNoteTitle(parsed.report_name || "");
    setNoteBody(parsed.note_body || "");
  }

  async function fetchData() {
    if (!documentId) {
      throw new Error("Missing document id.");
    }

    const meResponse = await api.get<CurrentUser>("/auth/me");
    setCurrentUser(meResponse.data);

    const documentResponse = await api.get<DocumentResponse>(`/documents/${documentId}`);

    if (!documentResponse.data?.parsed_data) {
      throw new Error("Document loaded, but parsed_data is missing.");
    }

    const isDischargeSummary =
      documentResponse.data.section === "discharge_summary" ||
      documentResponse.data.parsed_data?.report_type === "Discharge summary" ||
      documentResponse.data.parsed_data?.report_type === "discharge_summary";

    if (isDischargeSummary) {
      router.replace(`/documents/${documentId}/discharge`);
      return;
    }

    setDocumentData(documentResponse.data);
    hydrateForm(documentResponse.data);
  }

  useEffect(() => {
    async function init() {
      try {
        setLoading(true);
        setError("");
        await fetchData();
      } catch (err) {
        setError(getErrorMessage(err, t("couldNotLoadDocument")));
      } finally {
        setLoading(false);
      }
    }

    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const parsed = documentData?.parsed_data;
  const isNote = documentData?.section === "notes";
  const dischargePayload = parseDischargePayload(parsed?.note_body);
  const isDischargeSummary =
    documentData?.section === "discharge_summary" ||
    parsed?.report_type === "Discharge summary" ||
    Boolean(dischargePayload);

  const canEditStructured = currentUser?.role === "doctor" || currentUser?.role === "admin";
  const canVerify = currentUser?.role === "doctor" || currentUser?.role === "admin";
  const canEditNote = Boolean(documentData?.can_edit_note) || currentUser?.role === "admin";
  const canDelete =
    Boolean(currentUser && documentData && currentUser.id === documentData.uploaded_by_user_id) ||
    currentUser?.role === "admin";

  const abnormalLabs = useMemo(() => {
    return (documentData?.parsed_data.labs || []).filter((lab) => {
      if (isNilValue(lab.value)) return false;
      return lab.is_abnormal || isAbnormalFlag(lab.flag);
    });
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
        typeof rawContentType === "string"
          ? rawContentType
          : documentData.content_type || "application/octet-stream";

      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);

      window.open(fileUrl, "_blank", "noopener,noreferrer");

      window.setTimeout(() => {
        window.URL.revokeObjectURL(fileUrl);
      }, 60_000);
    } catch (err) {
      setError(getErrorMessage(err, "Could not open original file."));
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

      if (currentUser?.role === "patient") {
        router.push("/my-records");
        return;
      }

      if (documentData.patient_id) {
        router.push(`/patients/${documentData.patient_id}`);
        return;
      }

      router.push("/my-records");
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
            value: cleanLabValueForSave(lab.value || null),
            flag: isNilValue(lab.value) || !lab.reference_range?.trim() ? null : lab.flag || null,
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
      setError(t("noteBodyRequired"));
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

  if (loading) {
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
          <span className="muted-text">{t("loadingStructuredDocument")}</span>
        </div>
      </main>
    );
  }

  if (!currentUser || !documentData || !parsed) {
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
        <div className="soft-card-tight" style={{ padding: 22, maxWidth: 620 }}>
          <div style={{ fontSize: 22, fontWeight: 950, marginBottom: 8 }}>
            {t("couldNotLoadDocument")}
          </div>

          <div className="muted-text" style={{ lineHeight: 1.6 }}>
            {t("documentLoadedBadFormat")}
          </div>

          {error ? (
            <div
              style={{
                marginTop: 14,
                padding: 14,
                borderRadius: 16,
                background: "var(--danger-bg)",
                color: "var(--danger-text)",
                border: "1px solid var(--danger-border)",
                fontWeight: 800,
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
              }}
            >
              {error}
            </div>
          ) : null}

          <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
            <button className="secondary-btn" onClick={() => router.push("/my-records")}>
              {t("backToMyRecords")}
            </button>

            <button className="secondary-btn" onClick={() => window.location.reload()}>
              {t("tryAgain")}
            </button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={parsed.report_name || documentData.filename || "Document"}
      subtitle={`${valueOrDash(parsed.patient_name)} · CNP ${valueOrDash(parsed.cnp)} · ${valueOrDash(
        parsed.report_type
      )} · ${t(parsed.is_verified ? "verified" : "unverified")}`}
      rightContent={
        <button className="secondary-btn" onClick={() => router.back()}>
          {t("back")}
        </button>
      }
    >
      <style jsx global>{`
        .document-lab-table {
          width: 100%;
          border-collapse: separate;
          border-spacing: 0;
        }

        .document-lab-table th {
          text-align: left;
          font-size: 12px;
          color: var(--muted);
          font-weight: 950;
          padding: 12px 14px;
          border-bottom: 1px solid var(--border);
          background: var(--panel-2);
        }

        .document-lab-table td {
          padding: 14px;
          border-bottom: 1px solid var(--border);
          vertical-align: middle;
        }

        .document-lab-table tr:last-child td {
          border-bottom: 0;
        }

        .document-lab-table tr.abnormal-row td {
          background: color-mix(in srgb, var(--danger-bg) 72%, transparent);
        }

        .document-lab-table tr.nil-row td {
          opacity: 0.82;
        }

        .document-edit-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
          gap: 20px;
        }

        @media (max-width: 900px) {
          .document-lab-table,
          .document-lab-table thead,
          .document-lab-table tbody,
          .document-lab-table th,
          .document-lab-table td,
          .document-lab-table tr {
            display: block;
          }

          .document-lab-table thead {
            display: none;
          }

          .document-lab-table tr {
            border-bottom: 1px solid var(--border);
            padding: 10px 0;
          }

          .document-lab-table td {
            border-bottom: 0;
            padding: 8px 12px;
          }

          .document-lab-table td::before {
            content: attr(data-label);
            display: block;
            color: var(--muted);
            font-size: 11px;
            font-weight: 900;
            margin-bottom: 4px;
          }
        }
      `}</style>

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
            <div style={{ fontSize: 24, fontWeight: 950, letterSpacing: "-0.05em" }}>{t("deleteThisReport")}</div>

            <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.65 }}>
              {t("deleteReportDesc")}
            </div>

            <div className="soft-card-tight" style={{ marginTop: 16, padding: 14, background: "var(--panel-2)" }}>
              <div style={{ fontWeight: 900 }}>{parsed.report_name || documentData.filename}</div>
              <div className="muted-text" style={{ marginTop: 5 }}>
                {t("uploadedBy")} {valueOrDash(documentData.uploaded_by?.full_name)}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
              <button className="secondary-btn" onClick={() => setConfirmDeleteOpen(false)} disabled={deleting}>
                {t("cancel")}
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
                {deleting ? t("deleting") : t("deleteReport")}
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
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: 999, background: parsed.is_verified ? "var(--success-text)" : "var(--warn-text)", flexShrink: 0 }} />
                <span style={{ fontSize: 12, fontWeight: 900, color: parsed.is_verified ? "var(--success-text)" : "var(--warn-text)" }}>
                  {t(parsed.is_verified ? "verified" : "unverified")}
                </span>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--muted)", flexShrink: 0 }} />
                <span style={{ fontSize: 12, fontWeight: 900, color: "var(--muted)" }}>{documentData.section}</span>
              </div>

              {!isNote && !isDischargeSummary && abnormalLabs.length > 0 && (
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--danger-text)", flexShrink: 0 }} />
                  <span style={{ fontSize: 12, fontWeight: 900, color: "var(--danger-text)" }}>{abnormalLabs.length} {t("abnormalCountLabel")}</span>
                </div>
              )}

              {isNote && (
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--muted)", flexShrink: 0 }} />
                  <span style={{ fontSize: 12, fontWeight: 900, color: "var(--muted)" }}>{t("clinicalNote")}</span>
                </div>
              )}

              {isDischargeSummary && (
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--muted)", flexShrink: 0 }} />
                  <span style={{ fontSize: 12, fontWeight: 900, color: "var(--muted)" }}>{t("dischargeSummaryLabel")}</span>
                </div>
              )}
            </div>

            <div className="muted-text" style={{ marginTop: 10, lineHeight: 1.6 }}>
              {t("uploadedBy")} {valueOrDash(documentData.uploaded_by?.full_name)} · {t("created")} {formatDate(parsed.created_at)}
              {parsed.last_edited_at ? ` · ${t("lastEdited")} ${formatDate(parsed.last_edited_at)}` : ""}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {!isNote && (
              <button className="secondary-btn" onClick={openOriginal} disabled={openingOriginal}>
                {openingOriginal ? t("opening") : t("openOriginal")}
              </button>
            )}

            {canVerify && !parsed.is_verified && (
              <button className="primary-btn" onClick={verifyDocument} disabled={verifying}>
                {verifying ? t("verifying") : t("verify")}
              </button>
            )}

            {!isNote && !isDischargeSummary && canEditStructured && (
              <button className={editMode ? "secondary-btn" : "primary-btn"} onClick={() => setEditMode((prev) => !prev)}>
                {editMode ? t("cancelEdit") : t("editStructuredData")}
              </button>
            )}

            {isNote && canEditNote && (
              <button className={noteEditMode ? "secondary-btn" : "primary-btn"} onClick={() => setNoteEditMode((prev) => !prev)}>
                {noteEditMode ? t("cancelEdit") : t("editNote")}
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
                {t("delete")}
              </button>
            )}
          </div>
        </div>
      </div>

      {isNote ? (
        <div className="soft-card" style={{ padding: 24 }}>
          {!noteEditMode ? (
            <>
              <SectionHeader title={parsed.report_name || t("clinicalNote")} />

              <div
                className="soft-card-tight"
                style={{
                  padding: 20,
                  background: "var(--panel)",
                  lineHeight: 1.8,
                  whiteSpace: "pre-wrap",
                }}
              >
                {parsed.note_body || t("noNoteBody")}
              </div>
            </>
          ) : (
            <form onSubmit={saveNote} style={{ display: "grid", gap: 14 }}>
              <input
                className="text-input"
                value={noteTitle}
                onChange={(event) => setNoteTitle(event.target.value)}
                placeholder={t("noteTitle")}
                disabled={savingNote}
              />

              <textarea
                className="text-input"
                value={noteBody}
                onChange={(event) => setNoteBody(event.target.value)}
                rows={16}
                placeholder={t("writeNote")}
                disabled={savingNote}
                style={{ resize: "vertical", lineHeight: 1.7 }}
              />

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button type="button" className="secondary-btn" onClick={() => setNoteEditMode(false)} disabled={savingNote}>
                  {t("cancel")}
                </button>
                <button type="submit" className="primary-btn" disabled={savingNote}>
                  {savingNote ? t("saving") : t("saveNote")}
                </button>
              </div>
            </form>
          )}
        </div>
      ) : isDischargeSummary ? (
        <div style={{ display: "grid", gap: 24 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 20,
            }}
          >
            <div className="soft-card" style={{ padding: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 18 }}>{t("patient")}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "18px 20px" }}>
                <MetaField label={t("name")} value={parsed.patient_name} />
                <MetaField label={t("dateOfBirth")} value={parsed.date_of_birth} />
                <MetaField label={t("age")} value={parsed.age} />
                <MetaField label={t("sex")} value={parsed.sex} />
                <MetaField label={t("cnp")} value={parsed.cnp} />
                <MetaField label={t("patientId")} value={parsed.patient_identifier} />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 18 }}>{t("documentDetails")}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "18px 20px" }}>
                <MetaField label={t("reportName")} value={parsed.report_name} />
                <MetaField label={t("reportType")} value={parsed.report_type} />
                <MetaField label={t("lab")} value={parsed.lab_name} />
                <MetaField label={t("referringDoctor")} value={parsed.referring_doctor} />
                <MetaField label={t("sourceLanguageLabel")} value={parsed.source_language} />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 18 }}>{t("dates")}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "18px 20px" }}>
                <MetaField label={t("collectedOn")} value={parsed.collected_on} />
                <MetaField label={t("reportedOn")} value={parsed.reported_on} />
                <MetaField label={t("registeredOn")} value={parsed.registered_on} />
                <MetaField label={t("generatedOn")} value={parsed.generated_on} />
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 22 }}>
            <SectionHeader
              title={t("structuredDischargeSummary")}
              subtitle={t("structuredDischargeSummaryDesc")}
            />

            {dischargePayload?.sections?.length ? (
              <div style={{ display: "grid", gap: 14 }}>
                {dischargePayload.sections.map((section, index) => (
                  <div
                    key={`${section.key}-${index}`}
                    className="soft-card-tight"
                    style={{
                      padding: 18,
                      background: "var(--panel-2)",
                      borderRadius: 22,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 12,
                        alignItems: "flex-start",
                        flexWrap: "wrap",
                        marginBottom: 10,
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 950, fontSize: 17, letterSpacing: "-0.03em" }}>
                          {section.title || t("clinicalSection")}
                        </div>

                        {section.original_titles?.length ? (
                          <div className="muted-text" style={{ marginTop: 5, fontSize: 12, fontWeight: 800 }}>
                            {t("originalHeadingLabel")} {section.original_titles.join(" · ")}
                          </div>
                        ) : null}
                      </div>

                      {section.confidence ? (
                        <StatusPill>{Math.round(section.confidence * 100)}% match</StatusPill>
                      ) : null}
                    </div>

                    <div
                      style={{
                        whiteSpace: "pre-wrap",
                        lineHeight: 1.65,
                        color: "var(--foreground)",
                        fontWeight: 650,
                      }}
                    >
                      {section.body}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                <div style={{ fontWeight: 900 }}>{t("noStructuredDischargeSections")}</div>
                <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                  {t("noStructuredDischargeSectionsDesc")}
                </div>
              </div>
            )}
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <SectionHeader title={t("auditTrail")} />

            <div style={{ display: "grid", gap: 12 }}>
              {(parsed.audit_logs || []).map((log, index) => (
                <div key={`${log.action}-${log.timestamp}-${index}`} className="soft-card-tight" style={{ padding: 16 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ fontWeight: 950 }}>{log.action}</div>
                    <div className="muted-text" style={{ fontSize: 12 }}>
                      {valueOrDash(log.actor)} · {formatDate(log.timestamp)}
                    </div>
                  </div>

                  {log.details && (
                    <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.55 }}>
                      {log.details}
                    </div>
                  )}
                </div>
              ))}

              {!parsed.audit_logs?.length && (
                <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                  <div className="muted-text">{t("noAuditActivity")}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : editMode ? (
        <form onSubmit={saveStructuredData} style={{ display: "grid", gap: 24 }}>
          <div className="document-edit-grid">
            <div className="soft-card" style={{ padding: 24 }}>
              <SectionHeader title={t("patient")} />

              <div style={{ display: "grid", gap: 12 }}>
                <TextInput label={t("patientNameLabel")} value={patientName} onChange={setPatientName} />
                <TextInput label={t("dateOfBirth")} value={dateOfBirth} onChange={setDateOfBirth} />
                <TextInput label={t("age")} value={age} onChange={setAge} />
                <TextInput label={t("sex")} value={sex} onChange={setSex} />
                <TextInput label={t("cnp")} value={cnp} onChange={setCnp} />
                <TextInput label={t("patientId")} value={patientIdentifier} onChange={setPatientIdentifier} />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <SectionHeader title={t("documentDetails")} />

              <div style={{ display: "grid", gap: 12 }}>
                <TextInput label={t("reportName")} value={reportName} onChange={setReportName} />
                <TextInput label={t("reportType")} value={reportType} onChange={setReportType} />
                <TextInput label={t("lab")} value={labName} onChange={setLabName} />
                <TextInput label={t("sampleType")} value={sampleType} onChange={setSampleType} />
                <TextInput label={t("referringDoctor")} value={referringDoctor} onChange={setReferringDoctor} />
                <TextInput label={t("sourceLanguageLabel")} value={sourceLanguage} onChange={setSourceLanguage} />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <SectionHeader title={t("dates")} />

              <div style={{ display: "grid", gap: 12 }}>
                <TextInput label={t("testDate")} value={testDate} onChange={setTestDate} />
                <TextInput label={t("collectedOn")} value={collectedOn} onChange={setCollectedOn} />
                <TextInput label={t("reportedOn")} value={reportedOn} onChange={setReportedOn} />
                <TextInput label={t("registeredOn")} value={registeredOn} onChange={setRegisteredOn} />
                <TextInput label={t("generatedOn")} value={generatedOn} onChange={setGeneratedOn} />
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <SectionHeader
              title={t("structuredData")}
              subtitle={t("labRowsEditHint")}
              right={
                <button type="button" className="secondary-btn" onClick={addLabRow}>
                  {t("addRow")}
                </button>
              }
            />

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
                    value={lab.display_name || ""}
                    onChange={(event) => updateLab(index, "display_name", event.target.value)}
                    placeholder={t("displayName")}
                  />

                  <input
                    className="text-input"
                    value={lab.raw_test_name || ""}
                    onChange={(event) => updateLab(index, "raw_test_name", event.target.value)}
                    placeholder={t("rawName")}
                  />

                  <select
                    className="text-input"
                    value={lab.category || "Alte analize"}
                    onChange={(event) => updateLab(index, "category", event.target.value)}
                  >
                    {CATEGORY_OPTIONS.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
                  </select>

                  <input
                    className="text-input"
                    value={lab.value || ""}
                    onChange={(event) => updateLab(index, "value", event.target.value)}
                    placeholder={t("valueNil")}
                  />

                  <input
                    className="text-input"
                    value={lab.reference_range || ""}
                    onChange={(event) => updateLab(index, "reference_range", event.target.value)}
                    placeholder={t("reference")}
                  />

                  <input
                    className="text-input"
                    value={lab.unit || ""}
                    onChange={(event) => updateLab(index, "unit", event.target.value)}
                    placeholder={t("unit")}
                  />

                  <div style={{ display: "flex", gap: 8 }}>
                    <select
                      className="text-input"
                      value={lab.flag || ""}
                      onChange={(event) => updateLab(index, "flag", event.target.value)}
                      style={{ minWidth: 110 }}
                    >
                      <option value="">{t("noFlag")}</option>
                      <option value="Normal">Normal</option>
                      <option value="High">High</option>
                      <option value="Low">Low</option>
                      <option value="Abnormal">Abnormal</option>
                    </select>

                    <button type="button" className="secondary-btn" onClick={() => removeLabRow(index)}>
                      {t("remove")}
                    </button>
                  </div>
                </div>
              ))}

              {!labs.length && (
                <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                  <div className="muted-text">{t("noStructuredLabRowsYet")}</div>
                </div>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
              <button
                type="button"
                className="secondary-btn"
                disabled={saving}
                onClick={() => {
                  hydrateForm(documentData);
                  setEditMode(false);
                }}
              >
                {t("cancel")}
              </button>

              <button type="submit" className="primary-btn" disabled={saving}>
                {saving ? t("saving") : t("saveStructuredData")}
              </button>
            </div>
          </div>
        </form>
      ) : (
        <div style={{ display: "grid", gap: 24 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 20,
            }}
          >
            <div className="soft-card" style={{ padding: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 18 }}>{t("patient")}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "18px 20px" }}>
                <MetaField label={t("name")} value={parsed.patient_name} />
                <MetaField label={t("dateOfBirth")} value={parsed.date_of_birth} />
                <MetaField label={t("age")} value={parsed.age} />
                <MetaField label={t("sex")} value={parsed.sex} />
                <MetaField label={t("cnp")} value={parsed.cnp} />
                <MetaField label={t("patientId")} value={parsed.patient_identifier} />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 18 }}>{t("documentDetails")}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "18px 20px" }}>
                <MetaField label={t("reportName")} value={parsed.report_name} />
                <MetaField label={t("reportType")} value={parsed.report_type} />
                <MetaField label={t("lab")} value={parsed.lab_name} />
                <MetaField label={t("sampleType")} value={parsed.sample_type} />
                <MetaField label={t("referringDoctor")} value={parsed.referring_doctor} />
                <MetaField label={t("sourceLanguageLabel")} value={parsed.source_language} />
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 18 }}>{t("dates")}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "18px 20px" }}>
                <MetaField label={t("testDate")} value={parsed.test_date} />
                <MetaField label={t("collectedOn")} value={parsed.collected_on} />
                <MetaField label={t("reportedOn")} value={parsed.reported_on} />
                <MetaField label={t("registeredOn")} value={parsed.registered_on} />
                <MetaField label={t("generatedOn")} value={parsed.generated_on} />
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <SectionHeader
              title={t("structuredData")}
              subtitle={`${parsed.labs?.length || 0} ${t("structuredLabRowsExtracted")}`}
            />

            {orderedGroupedLabs.length > 0 ? (
              <div style={{ display: "grid", gap: 22 }}>
                {orderedGroupedLabs.map(({ category, rows }) => (
                  <div key={category}>
                    <div
                      style={{
                        fontWeight: 950,
                        letterSpacing: "-0.03em",
                        marginBottom: 10,
                        textTransform: "uppercase",
                        fontSize: 13,
                        color: "var(--muted)",
                      }}
                    >
                      {category}
                    </div>

                    <div
                      className="soft-card-tight"
                      style={{
                        padding: 0,
                        overflow: "hidden",
                      }}
                    >
                      <table className="document-lab-table">
                        <thead>
                          <tr>
                            <th style={{ width: "38%" }}>{t("test")}</th>
                            <th>{t("value")}</th>
                            <th>{t("unit")}</th>
                            <th>{t("reference")}</th>
                            <th>{t("flag")}</th>
                          </tr>
                        </thead>

                        <tbody>
                          {rows.map((lab) => {
                            const nil = isNilValue(lab.value);
                            const abnormal = !nil && (lab.is_abnormal || isAbnormalFlag(lab.flag));
                            const flagStyle = getFlagStyle(lab.flag, lab.value);

                            return (
                              <tr
                                key={lab.id}
                                className={`${abnormal ? "abnormal-row" : ""} ${nil ? "nil-row" : ""}`}
                              >
                                <td data-label={t("test")}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                    {abnormal && (
                                      <span
                                        style={{
                                          width: 9,
                                          height: 9,
                                          borderRadius: 999,
                                          background: "var(--danger-text)",
                                          flex: "0 0 auto",
                                        }}
                                      />
                                    )}
                                    {nil && (
                                      <span
                                        style={{
                                          width: 9,
                                          height: 9,
                                          borderRadius: 999,
                                          background: "var(--muted)",
                                          flex: "0 0 auto",
                                        }}
                                      />
                                    )}

                                    <div style={{ fontWeight: 950 }}>{bestDisplayName(lab)}</div>
                                  </div>
                                </td>

                                <td data-label={t("value")}>
                                  <span style={{ fontWeight: 950 }}>{displayLabValue(lab.value)}</span>
                                </td>

                                <td data-label={t("unit")}>
                                  <span className="muted-text" style={{ fontWeight: 850 }}>
                                    {valueOrDash(lab.unit)}
                                  </span>
                                </td>

                                <td data-label={t("reference")}>
                                  <span className="muted-text" style={{ fontWeight: 850 }}>
                                    {valueOrDash(lab.reference_range)}
                                  </span>
                                </td>

                                <td data-label={t("flag")}>
                                  {nil ? (
                                    <span
                                      style={{
                                        display: "inline-flex",
                                        padding: "6px 10px",
                                        borderRadius: 999,
                                        border: "1px solid var(--border)",
                                        background: "var(--panel-2)",
                                        color: "var(--muted)",
                                        fontSize: 12,
                                        fontWeight: 950,
                                      }}
                                    >
                                      nil
                                    </span>
                                  ) : (
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
                                      {hasDisplayableFlag(lab.flag) ? lab.flag : "—"}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="soft-card-tight" style={{ padding: 18, background: "var(--panel-2)" }}>
                <div style={{ fontWeight: 900 }}>{t("noStructuredLabs")}</div>
                <div className="muted-text" style={{ marginTop: 6, lineHeight: 1.6 }}>
                  {t("noStructuredLabsHint")}
                </div>
              </div>
            )}
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <SectionHeader title={t("auditTrail")} />

            <div style={{ display: "grid", gap: 12 }}>
              {(parsed.audit_logs || []).map((log, index) => (
                <div key={`${log.action}-${log.timestamp}-${index}`} className="soft-card-tight" style={{ padding: 16 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ fontWeight: 950 }}>{log.action}</div>
                    <div className="muted-text" style={{ fontSize: 12 }}>
                      {valueOrDash(log.actor)} · {formatDate(log.timestamp)}
                    </div>
                  </div>

                  {log.details && (
                    <div className="muted-text" style={{ marginTop: 8, lineHeight: 1.55 }}>
                      {log.details}
                    </div>
                  )}
                </div>
              ))}

              {!parsed.audit_logs?.length && (
                <div className="soft-card-tight" style={{ padding: 16, background: "var(--panel-2)" }}>
                  <div className="muted-text">{t("noAuditActivity")}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
