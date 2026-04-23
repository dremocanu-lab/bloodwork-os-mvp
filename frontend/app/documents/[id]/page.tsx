"use client";

import { useEffect, useMemo, useState } from "react";
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

function sectionTitle(section?: string | null) {
  if (section === "bloodwork") return "Bloodwork";
  if (section === "scans") return "Scans";
  if (section === "other") return "Other";
  return "Documents";
}

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params?.id as string;

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
    const response = await api.get<DocumentResponse>(`/documents/${documentId}`);
    setDocumentData(response.data);
    setNoteTitle(response.data.parsed_data.report_name || "");
    setNoteBody(response.data.parsed_data.note_body || "");
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;

      try {
        setError("");
        await fetchDocument();
      } catch (err) {
        setError(getErrorMessage(err, "Failed to load record."));
      } finally {
        setLoading(false);
      }
    };

    init();
  }, [documentId]);

  const isNote = documentData?.section === "notes";
  const isAuthor =
    !!currentUser &&
    !!documentData &&
    currentUser.role === "doctor" &&
    currentUser.id === documentData.uploaded_by_user_id;

  const linkedDocuments = documentData?.parsed_data.linked_documents || [];
  const availableLinkableDocuments = documentData?.parsed_data.available_linkable_documents || [];

  const linkedByTab = useMemo(() => {
    return {
      bloodwork: linkedDocuments.filter((doc) => doc.section === "bloodwork"),
      scans: linkedDocuments.filter((doc) => doc.section === "scans"),
      other: linkedDocuments.filter((doc) => doc.section === "other"),
    };
  }, [linkedDocuments]);

  const availableByTab = useMemo(() => {
    return {
      bloodwork: availableLinkableDocuments.filter((doc) => doc.section === "bloodwork"),
      scans: availableLinkableDocuments.filter((doc) => doc.section === "scans"),
      other: availableLinkableDocuments.filter((doc) => doc.section === "other"),
    };
  }, [availableLinkableDocuments]);

  const saveNote = async () => {
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
      setError(getErrorMessage(err, "Failed to save note."));
    } finally {
      setSavingNote(false);
    }
  };

  const linkDocument = async (linkedDocumentId: number) => {
    if (!documentData) return;

    try {
      setLinking(linkedDocumentId);
      setError("");
      await api.post(`/documents/${documentData.document_id}/links`, {
        linked_document_id: linkedDocumentId,
      });
      await fetchDocument();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to link document."));
    } finally {
      setLinking(null);
    }
  };

  const unlinkDocument = async (linkedDocumentId: number) => {
    if (!documentData) return;

    try {
      setUnlinking(linkedDocumentId);
      setError("");
      await api.delete(`/documents/${documentData.document_id}/links/${linkedDocumentId}`);
      await fetchDocument();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to unlink document."));
    } finally {
      setUnlinking(null);
    }
  };

  if (loading || !currentUser || !documentData) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading record...</p>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={valueOrDash(documentData.parsed_data.report_name || documentData.filename)}
      subtitle={isNote ? "Clinical Note" : valueOrDash(documentData.parsed_data.report_type)}
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

      {isNote ? (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "0.9fr 1.1fr",
              gap: 20,
              marginBottom: 24,
            }}
          >
            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 16 }}>Patient</div>

              <div className="soft-card-tight" style={{ padding: 16 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>Name</div>
                <div style={{ fontWeight: 800, marginTop: 6 }}>
                  {valueOrDash(documentData.parsed_data.patient_name)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 16, marginTop: 12 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>Patient ID</div>
                <div style={{ fontWeight: 800, marginTop: 6 }}>
                  {valueOrDash(documentData.parsed_data.patient_identifier)}
                </div>
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 16 }}>Note Details</div>

              <div style={{ display: "grid", gap: 12 }}>
                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text" style={{ fontSize: 12 }}>Doctor</div>
                  <div style={{ fontWeight: 800, marginTop: 6 }}>
                    {valueOrDash(documentData.uploaded_by?.full_name)}
                  </div>
                </div>

                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text" style={{ fontSize: 12 }}>Department</div>
                  <div style={{ fontWeight: 800, marginTop: 6 }}>
                    {valueOrDash(documentData.uploaded_by?.department)}
                  </div>
                </div>

                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text" style={{ fontSize: 12 }}>Hospital</div>
                  <div style={{ fontWeight: 800, marginTop: 6 }}>
                    {valueOrDash(documentData.uploaded_by?.hospital_name)}
                  </div>
                </div>

                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text" style={{ fontSize: 12 }}>Created</div>
                  <div style={{ fontWeight: 800, marginTop: 6 }}>
                    {prettyDateTime(documentData.parsed_data.created_at || documentData.parsed_data.test_date)}
                  </div>
                </div>

                {!!documentData.parsed_data.last_edited_at && (
                  <div className="soft-card-tight" style={{ padding: 16 }}>
                    <div className="muted-text" style={{ fontSize: 12 }}>Last Edited</div>
                    <div style={{ fontWeight: 800, marginTop: 6 }}>
                      {prettyDateTime(documentData.parsed_data.last_edited_at)}
                    </div>
                  </div>
                )}
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
              }}
            >
              <div className="section-title">Note</div>

              {isAuthor && !editing && (
                <button className="secondary-btn" onClick={() => setEditing(true)}>
                  Edit
                </button>
              )}

              {isAuthor && editing && (
                <div style={{ display: "flex", gap: 10 }}>
                  <button
                    className="secondary-btn"
                    onClick={() => {
                      setEditing(false);
                      setNoteTitle(documentData.parsed_data.report_name || "");
                      setNoteBody(documentData.parsed_data.note_body || "");
                    }}
                  >
                    Cancel
                  </button>
                  <button className="primary-btn" onClick={saveNote} disabled={savingNote}>
                    {savingNote ? "Saving..." : "Save"}
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
                    placeholder="Note title"
                  />
                  <textarea
                    className="text-input"
                    value={noteBody}
                    onChange={(e) => setNoteBody(e.target.value)}
                    rows={16}
                    placeholder="Write note..."
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
            <div className="section-title" style={{ marginBottom: 16 }}>Linked Records</div>

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
              {linkedByTab[activeLinkTab].map((doc) => (
                <div key={doc.id} className="soft-card-tight" style={{ padding: 16 }}>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1.25fr auto",
                      gap: 16,
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 800 }}>{valueOrDash(doc.report_name || doc.filename)}</div>
                      <div className="muted-text" style={{ marginTop: 6 }}>
                        {valueOrDash(doc.report_type)} · {valueOrDash(doc.test_date)}
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 8 }}>
                      <button className="secondary-btn" onClick={() => router.push(`/documents/${doc.id}`)}>
                        Open
                      </button>

                      {isAuthor && (
                        <button
                          className="secondary-btn"
                          onClick={() => unlinkDocument(doc.id)}
                          disabled={unlinking === doc.id}
                        >
                          {unlinking === doc.id ? "Removing..." : "Remove"}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {!linkedByTab[activeLinkTab].length && (
                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text">No linked {sectionTitle(activeLinkTab).toLowerCase()} yet.</div>
                </div>
              )}
            </div>

            {isAuthor && (
              <>
                <div className="section-title" style={{ marginBottom: 14 }}>Add Linked {sectionTitle(activeLinkTab)}</div>

                <div style={{ display: "grid", gap: 12 }}>
                  {availableByTab[activeLinkTab]
                    .filter((doc) => !doc.is_linked)
                    .map((doc) => (
                      <div key={doc.id} className="soft-card-tight" style={{ padding: 16 }}>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "1.2fr auto",
                            gap: 16,
                            alignItems: "center",
                          }}
                        >
                          <div>
                            <div style={{ fontWeight: 800 }}>{valueOrDash(doc.report_name || doc.filename)}</div>
                            <div className="muted-text" style={{ marginTop: 6 }}>
                              {valueOrDash(doc.report_type)} · {valueOrDash(doc.test_date)}
                            </div>
                          </div>

                          <button
                            className="primary-btn"
                            onClick={() => linkDocument(doc.id)}
                            disabled={linking === doc.id}
                          >
                            {linking === doc.id ? "Adding..." : "Add"}
                          </button>
                        </div>
                      </div>
                    ))}

                  {!availableByTab[activeLinkTab].filter((doc) => !doc.is_linked).length && (
                    <div className="soft-card-tight" style={{ padding: 16 }}>
                      <div className="muted-text">No additional {sectionTitle(activeLinkTab).toLowerCase()} available to link.</div>
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
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gap: 14,
              marginBottom: 20,
            }}
          >
            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 14 }}>Patient</div>

              <div className="soft-card-tight" style={{ padding: 16 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>Name</div>
                <div style={{ marginTop: 6, fontWeight: 800 }}>
                  {valueOrDash(documentData.parsed_data.patient_name)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 16, marginTop: 12 }}>
                <div className="muted-text" style={{ fontSize: 12 }}>Patient ID</div>
                <div style={{ marginTop: 6, fontWeight: 800 }}>
                  {valueOrDash(documentData.parsed_data.patient_identifier)}
                </div>
              </div>
            </div>

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 14 }}>Document Details</div>

              <div style={{ display: "grid", gap: 12 }}>
                {[
                  ["Report Name", documentData.parsed_data.report_name],
                  ["Report Type", documentData.parsed_data.report_type],
                  ["Lab", documentData.parsed_data.lab_name],
                  ["Sample Type", documentData.parsed_data.sample_type],
                  ["Referring Doctor", documentData.parsed_data.referring_doctor],
                  ["Date", documentData.parsed_data.test_date],
                ].map(([label, value]) => (
                  <div key={label} className="soft-card-tight" style={{ padding: 16 }}>
                    <div className="muted-text" style={{ fontSize: 12 }}>{label}</div>
                    <div style={{ marginTop: 6, fontWeight: 700 }}>{valueOrDash(value as string)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 14 }}>Structured Data</div>

            <div style={{ display: "grid", gap: 12 }}>
              {documentData.parsed_data.labs.map((lab, index) => (
                <div key={`${lab.display_name}-${index}`} className="soft-card-tight" style={{ padding: 16 }}>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1.2fr 0.8fr 0.8fr 1fr 0.8fr",
                      gap: 12,
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <div className="muted-text" style={{ fontSize: 12 }}>Test</div>
                      <div style={{ fontWeight: 800, marginTop: 4 }}>
                        {valueOrDash(lab.display_name || lab.raw_test_name)}
                      </div>
                    </div>

                    <div>
                      <div className="muted-text" style={{ fontSize: 12 }}>Value</div>
                      <div style={{ fontWeight: 700, marginTop: 4 }}>{valueOrDash(lab.value)}</div>
                    </div>

                    <div>
                      <div className="muted-text" style={{ fontSize: 12 }}>Unit</div>
                      <div style={{ fontWeight: 700, marginTop: 4 }}>{valueOrDash(lab.unit)}</div>
                    </div>

                    <div>
                      <div className="muted-text" style={{ fontSize: 12 }}>Reference</div>
                      <div style={{ fontWeight: 700, marginTop: 4 }}>
                        {valueOrDash(lab.reference_range)}
                      </div>
                    </div>

                    <div>
                      <div className="muted-text" style={{ fontSize: 12 }}>Flag</div>
                      <div style={{ marginTop: 6 }}>
                        <span
                          style={{
                            display: "inline-flex",
                            padding: "4px 9px",
                            borderRadius: 999,
                            background:
                              String(lab.flag || "").toLowerCase() === "high" ||
                              String(lab.flag || "").toLowerCase() === "low"
                                ? "var(--warn-bg)"
                                : "var(--success-bg)",
                            color:
                              String(lab.flag || "").toLowerCase() === "high" ||
                              String(lab.flag || "").toLowerCase() === "low"
                                ? "var(--warn-text)"
                                : "var(--success-text)",
                            fontSize: 12,
                            fontWeight: 800,
                          }}
                        >
                          {valueOrDash(lab.flag)}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              {!documentData.parsed_data.labs.length && (
                <div className="soft-card-tight" style={{ padding: 16 }}>
                  <div className="muted-text">No structured lab values found.</div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}