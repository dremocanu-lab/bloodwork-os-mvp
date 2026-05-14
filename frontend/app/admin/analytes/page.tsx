"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/app-shell";
import { api, getErrorMessage } from "@/lib/api";
import { findAnalyteEntry } from "@/lib/analytes/match";

type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: "patient" | "doctor" | "admin";
  department?: string | null;
  hospital_name?: string | null;
};

type AnalyteGap = {
  canonical_name: string;
  raw_names: string[];
  count: number;
  last_document_id: number | null;
};

function Spinner({ size = 18 }: { size?: number }) {
  return (
    <>
      <style jsx>{`
        @keyframes bloodworkSpin { to { transform: rotate(360deg); } }
        .bloodwork-spinner {
          width: ${size}px; height: ${size}px;
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

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // clipboard not available
    }
  }

  return (
    <button
      type="button"
      className="secondary-btn"
      onClick={handleCopy}
      style={{ fontSize: 12, padding: "4px 10px", minWidth: 60 }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function AnalyteGapsPage() {
  const router = useRouter();

  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [gaps, setGaps] = useState<AnalyteGap[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function init() {
      try {
        setError("");
        const [meRes, gapsRes] = await Promise.all([
          api.get<CurrentUser>("/auth/me"),
          api.get<AnalyteGap[]>("/admin/analyte-gaps"),
        ]);

        if (meRes.data.role !== "admin") {
          router.replace("/assignments");
          return;
        }

        setCurrentUser(meRes.data);
        setGaps(gapsRes.data);
      } catch (err) {
        setError(getErrorMessage(err, "Could not load analyte gaps."));
      } finally {
        setLoading(false);
      }
    }
    init();
  }, []);

  // Cross-check: also flag gaps that DO match the Python catalog but miss the TS catalog
  const enrichedGaps = useMemo(() => {
    return gaps.map((gap) => ({
      ...gap,
      tsMatch: findAnalyteEntry(gap.canonical_name) !== null,
    }));
  }, [gaps]);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return enrichedGaps;
    return enrichedGaps.filter(
      (g) =>
        g.canonical_name.toLowerCase().includes(term) ||
        g.raw_names.some((r) => r.toLowerCase().includes(term)),
    );
  }, [enrichedGaps, query]);

  // Items the Python catalog missed (backend confirmed no match)
  const pythonMissed = filtered.filter((g) => !g.tsMatch);
  // Items Python missed but TS catalog has (catalog drift)
  const tsDriftOnly = filtered.filter((g) => g.tsMatch);

  if (loading || !currentUser) {
    return (
      <main className="app-page-bg" style={{ minHeight: "100vh", padding: 24, display: "grid", placeItems: "center" }}>
        <div className="soft-card-tight" style={{ padding: 22, display: "flex", gap: 12, alignItems: "center" }}>
          <Spinner size={20} />
          <span className="muted-text">Loading analyte gaps…</span>
        </div>
      </main>
    );
  }

  return (
    <AppShell
      user={currentUser}
      title="Analyte gaps"
      subtitle="Lab analyte names extracted from documents that are not in the catalog"
      rightContent={
        <button className="secondary-btn" onClick={() => router.push("/assignments")}>
          Back
        </button>
      }
    >
      {error && (
        <div className="soft-card-tight" style={{ marginBottom: 20, padding: 16, borderColor: "var(--danger-border)", background: "var(--danger-bg)", color: "var(--danger-text)" }}>
          {error}
        </div>
      )}

      {/* Summary strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14, marginBottom: 24 }}>
        <div className="soft-card-tight" style={{ padding: 18 }}>
          <div className="muted-text" style={{ fontSize: 12, fontWeight: 700 }}>Total gaps</div>
          <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.05em", marginTop: 6 }}>{gaps.length}</div>
          <div className="muted-text" style={{ fontSize: 12, marginTop: 4 }}>Distinct unrecognized names</div>
        </div>
        <div className="soft-card-tight" style={{ padding: 18 }}>
          <div className="muted-text" style={{ fontSize: 12, fontWeight: 700 }}>Python catalog only</div>
          <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.05em", marginTop: 6, color: "var(--danger-text)" }}>
            {gaps.filter((g) => findAnalyteEntry(g.canonical_name) === null).length}
          </div>
          <div className="muted-text" style={{ fontSize: 12, marginTop: 4 }}>Missing from both catalogs</div>
        </div>
        <div className="soft-card-tight" style={{ padding: 18 }}>
          <div className="muted-text" style={{ fontSize: 12, fontWeight: 700 }}>Catalog drift</div>
          <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.05em", marginTop: 6, color: "var(--warn-text)" }}>
            {gaps.filter((g) => findAnalyteEntry(g.canonical_name) !== null).length}
          </div>
          <div className="muted-text" style={{ fontSize: 12, marginTop: 4 }}>In TS catalog but not Python</div>
        </div>
        <div className="soft-card-tight" style={{ padding: 18 }}>
          <div className="muted-text" style={{ fontSize: 12, fontWeight: 700 }}>Total occurrences</div>
          <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.05em", marginTop: 6 }}>
            {gaps.reduce((sum, g) => sum + g.count, 0)}
          </div>
          <div className="muted-text" style={{ fontSize: 12, marginTop: 4 }}>Lab rows across all documents</div>
        </div>
      </div>

      <div className="soft-card" style={{ padding: 24 }}>
        <div style={{ marginBottom: 16 }}>
          <div className="section-title" style={{ marginBottom: 8 }}>Unknown analytes</div>
          <div className="muted-text" style={{ lineHeight: 1.6 }}>
            These canonical names appear in extracted lab results but were not matched by the Python catalog.
            Use the copy button to grab the exact name for adding to{" "}
            <code style={{ fontSize: 12, background: "var(--panel-2)", padding: "1px 5px", borderRadius: 4 }}>
              lab_catalog.py
            </code>{" "}
            or{" "}
            <code style={{ fontSize: 12, background: "var(--panel-2)", padding: "1px 5px", borderRadius: 4 }}>
              catalog.ts
            </code>.
          </div>
        </div>

        <input
          className="text-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by canonical name or raw name…"
          style={{ marginBottom: 16 }}
        />

        {pythonMissed.length > 0 && (
          <div style={{ marginBottom: 28 }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: "var(--danger-text)", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: "var(--danger-text)", display: "inline-block" }} />
              Missing from both catalogs ({pythonMissed.length})
            </div>
            <GapTable rows={pythonMissed} router={router} />
          </div>
        )}

        {tsDriftOnly.length > 0 && (
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, color: "var(--warn-text)", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: "var(--warn-text)", display: "inline-block" }} />
              In TS catalog only — Python needs synonym ({tsDriftOnly.length})
            </div>
            <GapTable rows={tsDriftOnly} router={router} />
          </div>
        )}

        {filtered.length === 0 && (
          <div style={{ padding: "32px 0", textAlign: "center" }}>
            <div style={{ fontWeight: 700, color: "var(--text)", marginBottom: 8 }}>
              {query ? "No gaps match this filter." : "No analyte gaps found."}
            </div>
            <div className="muted-text">
              {query ? "Try a different search term." : "All extracted analyte names are recognized by the catalog."}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

type GapRow = AnalyteGap & { tsMatch: boolean };

function GapTable({ rows, router }: { rows: GapRow[]; router: ReturnType<typeof useRouter> }) {
  return (
    <div style={{ borderTop: "1px solid var(--border)" }}>
      {/* Header */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 2fr 64px 80px 80px",
          gap: "0 16px",
          padding: "8px 0",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {["Canonical name", "Seen as (raw names)", "Count", "Document", ""].map((h) => (
          <span key={h} style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
            {h}
          </span>
        ))}
      </div>

      {rows.map((gap) => (
        <div
          key={gap.canonical_name}
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 2fr 64px 80px 80px",
            gap: "0 16px",
            padding: "11px 0",
            borderBottom: "1px solid var(--border)",
            alignItems: "center",
          }}
        >
          {/* Canonical name + copy */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span
              style={{
                fontWeight: 600,
                fontSize: 13,
                color: "var(--text)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {gap.canonical_name}
            </span>
          </div>

          {/* Raw names */}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {gap.raw_names.length > 0
              ? gap.raw_names.map((r) => (
                  <span
                    key={r}
                    style={{
                      padding: "1px 7px",
                      borderRadius: 4,
                      fontSize: 11,
                      background: "var(--panel-2)",
                      color: "var(--muted)",
                      border: "1px solid var(--border)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {r}
                  </span>
                ))
              : <span className="muted-text" style={{ fontSize: 12 }}>—</span>}
          </div>

          {/* Count */}
          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text)" }}>{gap.count}</span>

          {/* Last document link */}
          <span>
            {gap.last_document_id ? (
              <button
                type="button"
                className="secondary-btn"
                style={{ fontSize: 12, padding: "4px 10px" }}
                onClick={() => router.push(`/documents/${gap.last_document_id}`)}
              >
                #{gap.last_document_id}
              </button>
            ) : (
              <span className="muted-text" style={{ fontSize: 12 }}>—</span>
            )}
          </span>

          {/* Copy */}
          <CopyButton text={gap.canonical_name} />
        </div>
      ))}
    </div>
  );
}
