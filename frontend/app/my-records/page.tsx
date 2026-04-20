"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
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

type AccessRequest = {
  id: number;
  doctor_user_id: number;
  doctor_name: string | null;
  doctor_email: string | null;
  status: string;
  requested_at: string;
  responded_at?: string | null;
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

type MyProfileResponse = {
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

const sectionOptions = [
  { key: "bloodwork", label: "Bloodwork" },
  { key: "medications", label: "Medications" },
  { key: "scans", label: "Scans" },
  { key: "hospitalizations", label: "Hospitalizations" },
  { key: "other", label: "Other" },
] as const;

export default function MyRecordsPage() {
  const router = useRouter();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [profile, setProfile] = useState<MyProfileResponse | null>(null);
  const [accessRequests, setAccessRequests] = useState<AccessRequest[]>([]);
  const [activeTab, setActiveTab] = useState<string>("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadSection, setUploadSection] = useState("bloodwork");
  const [uploading, setUploading] = useState(false);
  const [respondingRequestId, setRespondingRequestId] = useState<number | null>(null);

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

  const pendingRequests = useMemo(
    () => accessRequests.filter((request) => request.status === "pending").length,
    [accessRequests]
  );

  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "bloodwork", label: "Bloodwork" },
    { key: "medications", label: "Medications" },
    { key: "scans", label: "Scans" },
    { key: "hospitalizations", label: "Hospitalizations" },
    { key: "other", label: "Other" },
    { key: "access-requests", label: "Doctor Requests" },
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
      const response = await api.get<MyProfileResponse>("/my/profile");
      setProfile(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load your profile."));
    }
  };

  const fetchAccessRequests = async () => {
    try {
      const response = await api.get<AccessRequest[]>("/my/access-requests");
      setAccessRequests(response.data);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to load access requests."));
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

  const respondToRequest = async (requestId: number, status: "approved" | "denied") => {
    try {
      setRespondingRequestId(requestId);
      setError("");

      await api.post(`/access-requests/${requestId}/respond`, {
        status,
      });

      await fetchAccessRequests();
      await fetchProfile();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to respond to request."));
    } finally {
      setRespondingRequestId(null);
    }
  };

  const logout = () => {
    localStorage.removeItem("access_token");
    router.push("/login");
  };

  useEffect(() => {
    const init = async () => {
      const me = await fetchMe();
      if (!me) return;

      if (me.role !== "patient") {
        router.push("/");
        return;
      }

      await Promise.all([fetchProfile(), fetchAccessRequests()]);
      setLoading(false);
    };

    init();
  }, []);

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <p className="muted-text">Loading your records...</p>
      </main>
    );
  }

  if (!profile) {
    return (
      <main className="app-page-bg" style={{ padding: 24 }}>
        <div className="soft-card" style={{ padding: 24, maxWidth: 640 }}>
          <p style={{ color: "#b91c1c", marginBottom: 16 }}>
            {error || "Could not load your records."}
          </p>
          <button className="secondary-btn" onClick={() => router.push("/login")}>
            Back
          </button>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="My Records"
      subtitle={`${profile.patient.full_name} · DOB ${valueOrDash(
        profile.patient.date_of_birth
      )}`}
      rightContent={
        <button className="secondary-btn" onClick={logout}>
          Log out
        </button>
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
        <StatCard label="Pending Requests" value={pendingRequests} accent="orange" />
        <StatCard
          label="Patient ID"
          value={valueOrDash(profile.patient.patient_identifier)}
          accent="green"
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 24, marginBottom: 24 }}>
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>
            Upload to My Record
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

        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>
            Profile Snapshot
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            <div className="soft-card-tight" style={{ padding: 14 }}>
              Full name: {profile.patient.full_name}
            </div>
            <div className="soft-card-tight" style={{ padding: 14 }}>
              DOB: {valueOrDash(profile.patient.date_of_birth)}
            </div>
            <div className="soft-card-tight" style={{ padding: 14 }}>
              Age: {valueOrDash(profile.patient.age)}
            </div>
            <div className="soft-card-tight" style={{ padding: 14 }}>
              Sex: {valueOrDash(profile.patient.sex)}
            </div>
            <div className="soft-card-tight" style={{ padding: 14 }}>
              CNP: {valueOrDash(profile.patient.cnp)}
            </div>
          </div>
        </div>
      </div>

      <PageTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 24 }}>
          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>
              My Sections
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                gap: 16,
              }}
            >
              <div className="soft-card-tight" style={{ padding: 18 }}>
                Bloodwork: {profile.sections.bloodwork.length}
              </div>
              <div className="soft-card-tight" style={{ padding: 18 }}>
                Medications: {profile.sections.medications.length}
              </div>
              <div className="soft-card-tight" style={{ padding: 18 }}>
                Scans: {profile.sections.scans.length}
              </div>
              <div className="soft-card-tight" style={{ padding: 18 }}>
                Hospitalizations: {profile.sections.hospitalizations.length}
              </div>
              <div className="soft-card-tight" style={{ padding: 18 }}>
                Other: {profile.sections.other.length}
              </div>
              <div className="soft-card-tight" style={{ padding: 18 }}>
                Doctors: {profile.doctor_access.length}
              </div>
            </div>
          </div>

          <div className="soft-card" style={{ padding: 24 }}>
            <div className="section-title" style={{ marginBottom: 18 }}>
              Doctors With Access
            </div>

            {profile.doctor_access.length === 0 ? (
              <p className="muted-text">No doctors currently have access.</p>
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

      {activeTab === "access-requests" && (
        <div className="soft-card" style={{ padding: 24 }}>
          <div className="section-title" style={{ marginBottom: 18 }}>
            Doctor Access Requests
          </div>

          {accessRequests.length === 0 ? (
            <p className="muted-text">No access requests.</p>
          ) : (
            <div style={{ display: "grid", gap: 14 }}>
              {accessRequests.map((request) => (
                <div key={request.id} className="soft-card-tight" style={{ padding: 18 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 16,
                      alignItems: "flex-start",
                      flexWrap: "wrap",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 700 }}>{valueOrDash(request.doctor_name)}</div>
                      <div className="muted-text" style={{ marginTop: 4, fontSize: 14 }}>
                        {valueOrDash(request.doctor_email)}
                      </div>
                      <div className="muted-text" style={{ marginTop: 8, fontSize: 13 }}>
                        Requested: {valueOrDash(request.requested_at)}
                      </div>
                      <div className="muted-text" style={{ marginTop: 4, fontSize: 13 }}>
                        Status: {valueOrDash(request.status)}
                      </div>
                    </div>

                    {request.status === "pending" && (
                      <div style={{ display: "flex", gap: 10 }}>
                        <button
                          className="primary-btn"
                          onClick={() => respondToRequest(request.id, "approved")}
                          disabled={respondingRequestId === request.id}
                        >
                          Approve
                        </button>
                        <button
                          className="secondary-btn"
                          onClick={() => respondToRequest(request.id, "denied")}
                          disabled={respondingRequestId === request.id}
                        >
                          Deny
                        </button>
                      </div>
                    )}
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