"use client";

/**
 * Canonical navigation (Phase 8E) — built from `ClinicalSection.
 * canonical_key`, NEVER the raw source heading. The reader API only
 * ever returns sections that survived `consolidate_segments`'s own
 * "drop non-substantive sections" rule, so every entry here already
 * has real content — no client-side emptiness filtering needed.
 */

import { CANONICAL_SECTION_LABELS, type ClinicalSection } from "@/lib/clinical-document-schema";

type Props = {
  sections: ClinicalSection[];
  activeSectionId: string | null;
  onSelect: (sectionId: string) => void;
};

export function DocumentOutline({ sections, activeSectionId, onSelect }: Props) {
  return (
    <nav aria-label="Document outline" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {sections.map((section) => {
        const active = section.id === activeSectionId;
        return (
          <button
            key={section.id}
            type="button"
            onClick={() => onSelect(section.id)}
            aria-current={active ? "true" : undefined}
            style={{
              textAlign: "left",
              padding: "8px 10px",
              borderRadius: "var(--r-md, 8px)",
              border: "none",
              background: active ? "var(--primary-soft)" : "transparent",
              color: active ? "var(--primary)" : "var(--text)",
              fontWeight: active ? 600 : 500,
              fontSize: "var(--fs-body)",
              cursor: "pointer",
            }}
          >
            {CANONICAL_SECTION_LABELS[section.canonical_key] || section.display_title}
          </button>
        );
      })}
    </nav>
  );
}
