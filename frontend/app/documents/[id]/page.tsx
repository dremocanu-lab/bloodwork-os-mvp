"use client";

import { useEffect, useMemo, useState } from "react";
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

type LabItem = {
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

type LinkedDocument = {
  id: number;
  filename: string;
  content_type?: string | null;
  report_name?: string | null;
  report_type?: string | null;
  lab_name?: string | null;
  sample_type?: string | null;
  referring_doctor?: string | null;
  test_date?: string | null;
  section: "bloodwork" | "scans" | "other" | string;
  is_verified: boolean;
  has_abnormal?: boolean;
  has_abnormal_labs?: boolean;
  reviewed_by_current_doctor?: boolean;
  is_linked?: boolean;
  uploaded_by?: UploadedBy | null;
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
    is_verified: boolean;
    verified_by?: string | null;
    verified_at?: string | null;
    last_edited_at?: string | null;
    created_at?: string | null;
    labs: LabItem[];
    linked_documents?: LinkedDocument[];
    available_linkable_documents?: LinkedDocument[];
  };
};

type LinkTab = "bloodwork" | "scans" | "other";

function prettyDateTime(value?: string | null) {
  if (!value) return "—";

  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;

  return d.toLocaleString();
}

function isAbnormalFlag(flag?: string | null) {
  return ["high", "low", "abnormal", "critical", "borderline"].includes(
    String(flag || "").trim().toLowerCase()
  );
}

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useLanguage();
  const documentId = params?.id as string;

  function sectionTitle(section?: string | null) {
    if (section === "bloodwork") return t("bloodwork");
    if (section === "scans") return t("scans");
    if (section === "other") return t("other");
    return t("documentsLabel");
  }

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documentData, setDocumentData] = useState<DocumentResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingNote, setSavingNote] = useState(false);
  const [linking, setLinking] = useState<number | null>(null);
  const [unlinking, setUnlinking] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [activeLinkTab, setActiveLinkTab] = useState<LinkTab>("bloodwork");
  const [error, setError] = useState("");

  async function fetchMe() {
    try {
      const response = await api.get<CurrentUser>("/auth/me");
      setCurrentUser(response.data);
      return response.data;
    } catch {
      localStorage.removeItem("access_token");
      router.push("/login");
      return null;
    }
  }

  async function fetchDocument() {
    const response = await api.get<DocumentResponse>(`/documents/${documentId}`);
    setDocumentData(response.data);
    setNoteTitle(response.data.parsed_data.report_name || "");
    setNoteBody(response.data.parsed_data.note_body || "");
  }

  useEffect(() => {
    async function init() {
      const me = await fetchMe();
      if (!me) return;

      try {
        setError("");
        await fetchDocument();
      } catch (err) {
        setError(getErrorMessage(err, t("failedLoadRecord")));
      } finally {
        setLoading(false);
      }
    }

    init();
  }, [documentId]);

  const isNote = documentData?.section === "notes";

  const isAuthor =
    !!currentUser &&
    !!documentData &&
    currentUser.role === "doctor" &&
    currentUser.id === documentData.uploaded_by_user_id;

  const abnormalLabs = useMemo(() => {
    return documentData?.parsed_data.labs.filter((lab) => isAbnormalFlag(lab.flag)) || [];
  }, [documentData]);

  const hasAbnormalLabs = abnormalLabs.length > 0;

  const linkedDocuments = documentData?.parsed_data.linked_documents || [];
  const availableLinkableDocuments = documentData?.parsed_data.available_linkable_documents || [];

  const linkedByTab = useMemo(
    () => ({
      bloodwork: linkedDocuments.filter((doc) => doc.section === "bloodwork"),
      scans: linkedDocuments.filter((doc) => doc.section === "scans"),
      other: linkedDocuments.filter((doc) => doc.section === "other"),
    }),
    [linkedDocuments]
  );

  const availableByTab = useMemo(
    () => ({
      bloodwork: availableLinkableDocuments.filter((doc) => doc.section === "bloodwork"),
      scans: availableLinkableDocuments.filter((doc) => doc.section === "scans"),
      other: availableLinkableDocuments.filter((doc) => doc.section === "other"),
    }),
    [availableLinkableDocuments]
  );

  async function openOriginal(documentIdToOpen: number) {
    try {
      setError("");

      const response = await api.get(`/documents/${documentIdToOpen}/file`, {
        responseType: "blob",
      });

      const rawContentType = response.headers["content-type"];
      const contentType =
        typeof rawContentType === "string" ? rawContentType : "application/octet-stream";

      const blob = new Blob([response.data], { type: contentType });
      const fileUrl = window.URL.createObjectURL(blob);

      window.open(fileUrl, "_blank", "noopener,noreferrer");

      setTimeout(() => {
        window.URL.revokeObjectURL(fileUrl);
      }, 60_000);
    } catch (err) {
      setError(getErrorMessage(err, t("failedOpenOriginal")));
    }
  }

  async function saveNote() {
    if (!documentData) return;

    try {
      setSavingNote(true);
      setError("");

      await api.put(`/documents/${documentData.document_id}/note`, {
        title: noteTitle,
        content: noteBody,
      });

      await fetchDocument();
      setEditing(false);
    } catch (err) {
      setError(getErrorMessage(err, t("failedSaveNote")));
    } finally {
      setSavingNote(false);
    }
  }

  async function linkDocument(linkedDocumentId: number) {
    if (!documentData) return;

    try {
      setLinking(linkedDocumentId);
      setError("");

      await api.post(`/documents/${documentData.document_id}/links`, {
        linked_document_id: linkedDocumentId,
      });

      await fetchDocument();
    } catch (err) {
      setError(getErrorMessage(err, t("failedLinkDocument")));
    } finally {
      setLinking(null);
    }
  }

  async function unlinkDocument(linkedDocumentId: number) {
    if (!documentData) return;

    try {
      setUnlinking(linkedDocumentId);
      setError("");

      await api.delete(`/documents/${documentData.document_id}/links/${linkedDocumentId}`);
      await fetchDocument();
    } catch (err) {
      setError(getErrorMessage(err, t("failedUnlinkDocument")));
    } finally {
      setUnlinking(null);
    }
  }

  if (loading || !currentUser || !documentData) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">{t("loadingRecord")}</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={valueOrDash(documentData.parsed_data.report_name || documentData.filename)}
      subtitle={isNote ? t("clinicalNote") : valueOrDash(documentData.parsed_data.report_type)}
      rightContent={
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {!isNote && !!documentData.content_type && !!documentData.filename && (
            <button
              type="button"
              className="secondary-btn"
              onClick={() => openOriginal(documentData.document_id)}
            >
              {t("openOriginalFile")}
            </button>
          )}

          <button className="secondary-btn" onClick={() => router.back()}>
            {t("back")}
          </button>
        </div>
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

      {!isNote && hasAbnormalLabs && (
        <div
          className="soft-card"
          style={{
            padding: 20,
            marginBottom: 24,
            borderColor: "var(--danger-border)",
            background: "var(--danger-bg)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span
              style={{
                width: 12,
                height: 12,
                borderRadius: 999,
                background: "var(--danger-text)",
                display: "inline-flex",
              }}
            />
            <div style={{ fontWeight: 950, color: "var(--danger-text)", fontSize: 18 }}>
              {t("abnormalResultsInRecord")}
            </div>
          </div>

          <div className="muted-text" style={{ marginTop: 8 }}>
            {t("abnormalResultsInRecordDesc")}
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14 }}>
            {abnormalLabs.slice(0, 6).map((lab, index) => (
              <span
                key={`${lab.display_name}-${index}`}
                style={{
                  display: "inline-flex",
                  padding: "7px 10px",
                  borderRadius: 999,
                  background: "var(--danger-bg)",
                  color: "var(--danger-text)",
                  border: "1px solid var(--danger-border)",
                  fontWeight: 900,
                  fontSize: 12,
                }}
              >
                {valueOrDash(lab.display_name || lab.raw_test_name)} {valueOrDash(lab.value)}
                {lab.unit ? ` ${lab.unit}` : ""} · {valueOrDash(lab.flag)}
              </span>
            ))}
          </div>
        </div>
      )}

      {isNote ? (
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
              <div className="section-title" style={{ marginBottom: 16 }}>
                {t("patient")}
              </div>

              <div className="soft-card-tight" style={{ padding: 16 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>
                  {t("name")}
                </div>
                <div style={{ fontWeight: 800, marginTop: 6 }}>
                  {valueOrDash(documentData.parsed_data.patient_name)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 16, marginTop: 12 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>
                  {t("patientId")}
                </div>
                <div style={{ fontWeight: 800, marginTop: 6 }}>
                  {valueOrDash(documentData.parsed_data.patient_identifier)}
                </div>
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 16 }}>
                {t("noteDetails")}
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                {[
                  [t("doctor"), documentData.uploaded_by?.full_name],
                  [t("department"), documentData.uploaded_by?.department],
                  [t("hospital"), documentData.uploaded_by?.hospital_name],
                  [t("created"), prettyDateTime(documentData.parsed_data.created_at || documentData.parsed_data.test_date)],
                  ...(documentData.parsed_data.last_edited_at
                    ? [[t("lastEdited"), prettyDateTime(documentData.parsed_data.last_edited_at)]]
                    : []),
                ].map(([label, value]) => (
                  <div key={label} className="soft-card-tight" style={{ padding: 16 }}>
                    <div className="muted-text" style={{ fontSize: 12 }}>
                      {label}
                    </div>
                    <div style={{ fontWeight: 800, marginTop: 6 }}>
                      {valueOrDash(value as string)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24, marginBottom: 24 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                alignItems: "center",
                marginBottom: 16,
                flexWrap: "wrap",
              }}
            >
              <div className="section-title">{t("note")}</div>

              {isAuthor && !editing && (
                <button className="secondary-btn" onClick={() => setEditing(true)}>
                  {t("edit")}
                </button>
              )}

              {isAuthor && editing && (
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button
                    className="secondary-btn"
                    onClick={() => {
                      setEditing(false);
                      setNoteTitle(documentData.parsed_data.report_name || "");
                      setNoteBody(documentData.parsed_data.note_body || "");
                    }}
                  >
                    {t("cancel")}
                  </button>
                  <button className="primary-btn" onClick={saveNote} disabled={savingNote}>
                    {savingNote ? t("saving") : t("save")}
                  </button>
                </div>
              )}
            </div>

            <div style={{ display: "grid", gap: 12, marginBottom: 16 }}>
              {editing ? (
                <>
                  <input
                    className="text-input"
                    value={noteTitle}
                    onChange={(e) => setNoteTitle(e.target.value)}
                    placeholder={t("noteTitle")}
                  />
                  <textarea
                    className="text-input"
                    value={noteBody}
                    onChange={(e) => setNoteBody(e.target.value)}
                    rows={16}
                    placeholder={t("writeNote")}
                  />
                </>
              ) : (
                <div
                  className="soft-card-tight"
                  style={{
                    padding: 24,
                    minHeight: 260,
                    whiteSpace: "pre-wrap",
                    lineHeight: 1.8,
                    fontSize: 16,
                  }}
                >
                  {valueOrDash(documentData.parsed_data.note_body)}
                </div>
              )}
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 16 }}>
              {t("linkedRecords")}
            </div>

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
              {(["bloodwork", "scans", "other"] as LinkTab[]).map((tab) => (
                <button
                  key={tab}
                  className={activeLinkTab === tab ? "primary-btn" : "secondary-btn"}
                  onClick={() => setActiveLinkTab(tab)}
                >
                  {sectionTitle(tab)} ({linkedByTab[tab].length})
                </button>
              ))}
            </div>

            <div style={{ display: "grid", gap: 12, marginBottom: isAuthor ? 24 : 0 }}>
              {linkedByTab[activeLinkTab].map((doc) => {
                const linkedHasAbnormal = Boolean(doc.has_abnormal || doc.has_abnormal_labs);

                return (
                  <div
                    key={doc.id}
                    className="soft-card-tight"
                    style={{
                      padding: 16,
                      borderColor: linkedHasAbnormal ? "var(--danger-border)" : "var(--border)",
                    }}
                  >
                    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12 }}>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          {linkedHasAbnormal && (
                            <span
                              style={{
                                width: 10,
                                height: 10,
                                borderRadius: 999,
                                background: "var(--danger-text)",
                                display: "inline-flex",
                              }}
                            />
                          )}

                          <div style={{ fontWeight: 800 }}>{valueOrDash(doc.report_name || doc.filename)}</div>
                        </div>

                        {linkedHasAbnormal && (
                          <div style={{ marginTop: 8 }}>
                            <span
                              style={{
                                display: "inline-flex",
                                padding: "5px 10px",
                                borderRadius: 999,
                                background: "var(--danger-bg)",
                                color: "var(--danger-text)",
                                border: "1px solid var(--danger-border)",
                                fontSize: 12,
                                fontWeight: 900,
                              }}
                            >
                              {t("abnormalResults")}
                            </span>
                          </div>
                        )}

                        <div className="muted-text" style={{ marginTop: 6 }}>
                          {valueOrDash(doc.report_type)} · {valueOrDash(doc.test_date)}
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <button className="secondary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                          {t("open")}
                        </button>

                        {!doc.section.includes("notes") && !!doc.content_type && (
                          <button className="secondary-btn" onClick={() => openOriginal(doc.id)}>
                            {t("openOriginal")}
                          </button>
                        )}

                        {isAuthor && (
                          <button
                            className="secondary-btn"
                            onClick={() => unlinkDocument(doc.id)}
                            disabled={unlinking === doc.id}
                          >
                            {unlinking === doc.id ? t("removing") : t("remove")}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}

              {!linkedByTab[activeLinkTab].length && (
                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text">
                    {t("linkedRecordsEmptyPrefix")} {sectionTitle(activeLinkTab).toLowerCase()}{" "}
                    {t("linkedRecordsEmptySuffix")}
                  </div>
                </div>
              )}
            </div>

            {isAuthor && (
              <>
                <div className="section-title" style={{ marginBottom: 14 }}>
                  {t("addLinked")} {sectionTitle(activeLinkTab)}
                </div>

                <div style={{ display: "grid", gap: 12 }}>
                  {availableByTab[activeLinkTab]
                    .filter((doc) => !doc.is_linked)
                    .map((doc) => {
                      const availableHasAbnormal = Boolean(doc.has_abnormal || doc.has_abnormal_labs);

                      return (
                        <div
                          key={doc.id}
                          className="soft-card-tight"
                          style={{
                            padding: 16,
                            borderColor: availableHasAbnormal ? "var(--danger-border)" : "var(--border)",
                          }}
                        >
                          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12 }}>
                            <div>
                              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                {availableHasAbnormal && (
                                  <span
                                    style={{
                                      width: 10,
                                      height: 10,
                                      borderRadius: 999,
                                      background: "var(--danger-text)",
                                      display: "inline-flex",
                                    }}
                                  />
                                )}

                                <div style={{ fontWeight: 800 }}>{valueOrDash(doc.report_name || doc.filename)}</div>
                              </div>

                              {availableHasAbnormal && (
                                <div style={{ marginTop: 8 }}>
                                  <span
                                    style={{
                                      display: "inline-flex",
                                      padding: "5px 10px",
                                      borderRadius: 999,
                                      background: "var(--danger-bg)",
                                      color: "var(--danger-text)",
                                      border: "1px solid var(--danger-border)",
                                      fontSize: 12,
                                      fontWeight: 900,
                                    }}
                                  >
                                    {t("abnormalResults")}
                                  </span>
                                </div>
                              )}

                              <div className="muted-text" style={{ marginTop: 6 }}>
                                {valueOrDash(doc.report_type)} · {valueOrDash(doc.test_date)}
                              </div>
                            </div>

                            <div>
                              <button
                                className="primary-btn"
                                onClick={() => linkDocument(doc.id)}
                                disabled={linking === doc.id}
                              >
                                {linking === doc.id ? t("adding") : t("add")}
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}

                  {!availableByTab[activeLinkTab].filter((doc) => !doc.is_linked).length && (
                    <div className="soft-card-tight" style={{ padding: 16 }}>
                      <div className="muted-text">
                        {t("noAdditionalLinkedAvailablePrefix")} {sectionTitle(activeLinkTab).toLowerCase()}{" "}
                        {t("noAdditionalLinkedAvailableSuffix")}
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </>
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
              gap: 14,
              marginBottom: 20,
            }}
          >
            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 14 }}>
                {t("patient")}
              </div>

              <div className="soft-card-tight" style={{ padding: 16 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>
                  {t("name")}
                </div>
                <div style={{ marginTop: 6, fontWeight: 800 }}>
                  {valueOrDash(documentData.parsed_data.patient_name)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 16, marginTop: 12 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>
                  {t("patientId")}
                </div>
                <div style={{ marginTop: 6, fontWeight: 800 }}>
                  {valueOrDash(documentData.parsed_data.patient_identifier)}
                </div>
              </div>
            </div>

            <div
              className="soft-card"
              style={{
                padding: 24,
                borderColor: hasAbnormalLabs ? "var(--danger-border)" : "var(--border)",
              }}
            >
              <div className="section-title" style={{ marginBottom: 14 }}>
                {t("documentDetails")}
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                {[
                  [t("reportName"), documentData.parsed_data.report_name],
                  [t("reportType"), documentData.parsed_data.report_type],
                  [t("lab"), documentData.parsed_data.lab_name],
                  [t("sampleType"), documentData.parsed_data.sample_type],
                  [t("referringDoctor"), documentData.parsed_data.referring_doctor],
                  [t("date"), documentData.parsed_data.test_date],
                ].map(([label, value]) => (
                  <div key={label} className="soft-card-tight" style={{ padding: 16 }}>
                    <div className="muted-text" style={{ fontSize: 12 }}>
                      {label}
                    </div>
                    <div style={{ marginTop: 6, fontWeight: 700 }}>{valueOrDash(value as string)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 14 }}>
              {t("structuredData")}
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              {documentData.parsed_data.labs.map((lab, index) => {
                const abnormal = isAbnormalFlag(lab.flag);

                return (
                  <div
                    key={`${lab.display_name}-${index}`}
                    className="soft-card-tight"
                    style={{
                      padding: 16,
                      borderColor: abnormal ? "var(--danger-border)" : "var(--border)",
                      background: abnormal ? "var(--danger-bg)" : undefined,
                    }}
                  >
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                        gap: 12,
                        alignItems: "center",
                      }}
                    >
                      <div>
                        <div className="muted-text" style={{ fontSize: 12 }}>
                          {t("test")}
                        </div>
                        <div style={{ fontWeight: 800, marginTop: 4 }}>
                          {valueOrDash(lab.display_name || lab.raw_test_name)}
                        </div>
                      </div>

                      <div>
                        <div className="muted-text" style={{ fontSize: 12 }}>
                          {t("value")}
                        </div>
                        <div style={{ fontWeight: 700, marginTop: 4 }}>{valueOrDash(lab.value)}</div>
                      </div>

                      <div>
                        <div className="muted-text" style={{ fontSize: 12 }}>
                          {t("unit")}
                        </div>
                        <div style={{ fontWeight: 700, marginTop: 4 }}>{valueOrDash(lab.unit)}</div>
                      </div>

                      <div>
                        <div className="muted-text" style={{ fontSize: 12 }}>
                          {t("reference")}
                        </div>
                        <div style={{ fontWeight: 700, marginTop: 4 }}>{valueOrDash(lab.reference_range)}</div>
                      </div>

                      <div>
                        <div className="muted-text" style={{ fontSize: 12 }}>
                          {t("flag")}
                        </div>
                        <div style={{ marginTop: 6 }}>
                          <span
                            style={{
                              display: "inline-flex",
                              padding: "4px 9px",
                              borderRadius: 999,
                              background: abnormal ? "var(--danger-bg)" : "var(--success-bg)",
                              color: abnormal ? "var(--danger-text)" : "var(--success-text)",
                              border: abnormal ? "1px solid var(--danger-border)" : undefined,
                              fontSize: 12,
                              fontWeight: 900,
                            }}
                          >
                            {valueOrDash(lab.flag)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}

              {!documentData.parsed_data.labs.length && (
                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text">{t("noStructuredLabs")}</div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}