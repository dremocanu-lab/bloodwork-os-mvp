"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, getErrorMessage, valueOrDash } from "@/lib/api";
import AppShell from "@/components/app-shell";
import PageTabs from "@/components/page-tabs";
import StatCard from "@/components/stat-card";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
};

type SectionDocument = {
  id: number;
  filename: string;
  report_name: string | null;
  test_date: string | null;
  section: string;
  is_verified?: boolean;
};

type DoctorAccess = {
  doctor_user_id: number;
  doctor_name: string;
  doctor_email: string;
  granted_at: string;
};

type PatientProfileResponse = {
  patient: {
    id: number;
    full_name: string;
    date_of_birth?: string | null;
    age: string | null;
    sex: string | null;
    cnp?: string | null;
    patient_identifier?: string | null;
  };
  sections: {
    bloodwork: SectionDocument[];
    medications: SectionDocument[];
    scans: SectionDocument[];
    hospitalizations: SectionDocument[];
    other: SectionDocument[];
  };
  doctor_access: DoctorAccess[];
};

type AccessRequestResponse = {
  id: number;
  doctor_user_id: number;
  patient_id: number;
  status: string;
  requested_at: string;
};

const sectionOptions = [
  { key: "bloodwork", label: "Bloodwork" },
  { key: "medications", label: "Medications" },
  { key: "scans", label: "Scans" },
  { key: "hospitalizations", label: "Hospitalizations" },
  { key: "other", label: "Other" },
] as const;

export default function PatientProfilePage() {
  const params = useParams();
  const router = useRouter();
  const patientId = params?.id as string;

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<PatientProfileResponse | null>(null);
  const [activeTab, setActiveTab] = useState<string>("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [requestingAccess, setRequestingAccess] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [uploading, setUploading] = useState(false);

  const canUpload =
    currentUser?.role === "admin" || currentUser?.role === "doctor";
  const canRequestAccess = currentUser?.role === "doctor";

  const currentSectionDocs = useMemo(() => {
    if (!profile) return [];
    if (activeTab === "bloodwork") return profile.sections.bloodwork;
    if (activeTab === "medications") return profile.sections.medications;
    if (activeTab === "scans") return profile.sections.scans;
    if (activeTab === "hospitalizations") return profile.sections.hospitalizations;
    if (activeTab === "other") return profile.sections.other;
    return [];
  }, [profile, activeTab]);

  const totalDocuments = useMemo(() => {
    if (!profile) return 0;
    return (
      profile.sections.bloodwork.length +
      profile.sections.medications.length +
      profile.sections.scans.length +
      profile.sections.hospitalizations.length +
      profile.sections.other.length
    );
  }, [profile]);

  const unverifiedCount = useMemo(() => {
    if (!profile) return 0;
    return [
      ...profile.sections.bloodwork,
      ...profile.sections.medications,
      ...profile.sections.scans,
      ...profile.sections.hospitalizations,
      ...profile.sections.other,
    ].filter((doc) => !doc.is_verified).length;
  }, [profile]);

  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "bloodwork", label: "Bloodwork" },
    { key: "medications", label: "Medications" },
    { key: "scans", label: "Scans" },
    { key: "hospitalizations", label: "Hospitalizations" },
    { key: "other", label: "Other" },
    { key: "access", label: "Access" },
  ];

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

  const fetchProfile = async () => {
    try {
      setLoading(true);
      setError("");
      const response = await api.get<PatientProfileResponse>(
        `/patients/${patientId}/profile`
      );
      setProfile(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load patient profile."));
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async () => {
    if (!uploadFile) {
      setError("Choose a file first.");
      return;
    }

    try {
      setUploading(true);
      setError("");

      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("patient_id", String(patientId));
      formData.append("section", uploadSection);

      await api.post("/upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
        timeout: 300000,
      });

      setUploadFile(null);
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to upload file."));
    } finally {
      setUploading(false);
    }
  };

  const requestAccess = async () => {
    try {
      setRequestingAccess(true);
      setError("");

      const response = await api.post<AccessRequestResponse>("/access-requests", {
        patient_id: Number(patientId),
      });

      alert(`Access request created. Status: ${response.data.status}`);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to request access."));
    } finally {
      setRequestingAccess(false);
    }
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;
      await fetchProfile();
    };

    init();
  }, [patientId]);

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading patient profile...</p>
      </main>
    );
  }

  if (!profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <div className="soft-card" style={{ padding: 24, maxWidth: 640 }}>
          <p style={{ color: "#b91c1c", marginBottom: 16 }}>
            {error || "Profile not found."}
          </p>
          <button className="secondary-btn" onClick={() => router.push("/")}>
            Back
          </button>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title={profile.patient.full_name}
      subtitle={`DOB ${valueOrDash(profile.patient.date_of_birth)} · Age ${valueOrDash(
        profile.patient.age
      )} · Sex ${valueOrDash(profile.patient.sex)}`}
      rightContent={
        <>
          <button className="secondary-btn" onClick={() => router.push("/")}>
            Back to Dashboard
          </button>
          {canRequestAccess && (
            <button
              className="secondary-btn"
              onClick={requestAccess}
              disabled={requestingAccess}
            >
              {requestingAccess ? "Requesting..." : "Request Access"}
            </button>
          )}
        </>
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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <StatCard label="Total Documents" value={totalDocuments} accent="violet" />
        <StatCard
          label="Doctors With Access"
          value={profile.doctor_access.length}
          accent="blue"
        />
        <StatCard label="Unverified" value={unverifiedCount} accent="orange" />
        <StatCard
          label="Patient ID"
          value={valueOrDash(profile.patient.patient_identifier)}
          accent="green"
        />
      </div>

      <PageTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 24 }}>
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>
              Patient Overview
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                gap: 16,
              }}
            >
              <div className="soft-card-tight" style={{ padding: 18 }}>
                <div className="muted-text" style={{ fontSize: 13 }}>Full name</div>
                <div style={{ marginTop: 8, fontWeight: 700 }}>{profile.patient.full_name}</div>
              </div>

              <div className="soft-card-tight" style={{ padding: 18 }}>
                <div className="muted-text" style={{ fontSize: 13 }}>Date of birth</div>
                <div style={{ marginTop: 8, fontWeight: 700 }}>
                  {valueOrDash(profile.patient.date_of_birth)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 18 }}>
                <div className="muted-text" style={{ fontSize: 13 }}>Age</div>
                <div style={{ marginTop: 8, fontWeight: 700 }}>
                  {valueOrDash(profile.patient.age)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 18 }}>
                <div className="muted-text" style={{ fontSize: 13 }}>Sex</div>
                <div style={{ marginTop: 8, fontWeight: 700 }}>
                  {valueOrDash(profile.patient.sex)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 18 }}>
                <div className="muted-text" style={{ fontSize: 13 }}>CNP</div>
                <div style={{ marginTop: 8, fontWeight: 700 }}>
                  {valueOrDash(profile.patient.cnp)}
                </div>
              </div>

              <div className="soft-card-tight" style={{ padding: 18 }}>
                <div className="muted-text" style={{ fontSize: 13 }}>Patient Identifier</div>
                <div style={{ marginTop: 8, fontWeight: 700 }}>
                  {valueOrDash(profile.patient.patient_identifier)}
                </div>
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gap: 24, alignContent: "start" }}>
            {canUpload && (
              <div className="soft-card" style={{ padding: 24 }}>
                <div className="section-title" style={{ marginBottom: 18 }}>
                  Upload to Profile
                </div>

                <div style={{ display: "grid", gap: 14 }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                      Section
                    </div>
                    <select
                      className="select-input"
                      value={uploadSection}
                      onChange={(e) => setUploadSection(e.target.value)}
                    >
                      {sectionOptions.map((section) => (
                        <option key={section.key} value={section.key}>
                          {section.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                      File
                    </div>
                    <input
                      className="text-input"
                      type="file"
                      accept=".pdf,.png,.jpg,.jpeg"
                      onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                    />
                  </div>

                  <button
                    className="primary-btn"
                    onClick={handleUpload}
                    disabled={uploading || !uploadFile}
                  >
                    {uploading ? "Uploading..." : "Upload"}
                  </button>
                </div>
              </div>
            )}

            <div className="soft-card" style={{ padding: 24 }}>
              <div className="section-title" style={{ marginBottom: 18 }}>
                Section Counts
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                <div className="soft-card-tight" style={{ padding: 14 }}>
                  Bloodwork: {profile.sections.bloodwork.length}
                </div>
                <div className="soft-card-tight" style={{ padding: 14 }}>
                  Medications: {profile.sections.medications.length}
                </div>
                <div className="soft-card-tight" style={{ padding: 14 }}>
                  Scans: {profile.sections.scans.length}
                </div>
                <div className="soft-card-tight" style={{ padding: 14 }}>
                  Hospitalizations: {profile.sections.hospitalizations.length}
                </div>
                <div className="soft-card-tight" style={{ padding: 14 }}>
                  Other: {profile.sections.other.length}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {["bloodwork", "medications", "scans", "hospitalizations", "other"].includes(
        activeTab
      ) && (
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>
            {activeTab.charAt(0).toUpperCase() + activeTab.slice(1)} Documents
          </div>

          {currentSectionDocs.length === 0 ? (
            <p className="muted-text">No documents in this section yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Filename</th>
                    <th>Report</th>
                    <th>Date</th>
                    <th>Verified</th>
                  </tr>
                </thead>
                <tbody>
                  {currentSectionDocs.map((doc) => (
                    <tr key={doc.id}>
                      <td>{doc.id}</td>
                      <td>{doc.filename}</td>
                      <td>{valueOrDash(doc.report_name)}</td>
                      <td>{valueOrDash(doc.test_date)}</td>
                      <td>{doc.is_verified ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === "access" && (
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>
            Doctor Access
          </div>

          {profile.doctor_access.length === 0 ? (
            <p className="muted-text">No doctor access records yet.</p>
          ) : (
            <div style={{ display: "grid", gap: 14 }}>
              {profile.doctor_access.map((doctor) => (
                <div key={doctor.doctor_user_id} className="soft-card-tight" style={{ padding: 18 }}>
                  <div style={{ fontWeight: 700 }}>{doctor.doctor_name}</div>
                  <div className="muted-text" style={{ marginTop: 4, fontSize: 14 }}>
                    {doctor.doctor_email}
                  </div>
                  <div className="muted-text" style={{ marginTop: 8, fontSize: 13 }}>
                    Granted: {valueOrDash(doctor.granted_at)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </AppShell>
  );
}