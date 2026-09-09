"use client";

/**
 * Patient workspace context bar.
 *
 * When a clinician opens a patient, Bragi becomes one patient workspace: this
 * bar holds identity and the record's tabs, and it sticks to the top so the
 * answer to "whose record is this?" is never more than a glance away.
 *
 * Deliberately compact - 52px including actions. The previous design spent a
 * 24px-padded card plus a second quick-action card row (roughly 200px of a
 * 900px screen) restating the name that was already in the page header.
 *
 * Pattern reference: Attio / Pipedrive / Zoho record headers - back, avatar,
 * name, inline meta, actions right, tabs directly beneath.
 */

import Link from "next/link";
import { ReactNode } from "react";
import { Tabs, type TabDef } from "@/components/ui";
import { IconChevronLeft } from "@/components/ui/icon";

export type PatientIdentity = {
  full_name: string;
  date_of_birth?: string | null;
  age?: string | null;
  sex?: string | null;
  cnp?: string | null;
  patient_identifier?: string | null;
};

function initials(name: string) {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("") || "P"
  );
}

export default function PatientContext({
  patient,
  ageLabel,
  backHref,
  backLabel,
  tabs,
  activeTab,
  onTabChange,
  actions,
  status,
}: {
  patient: PatientIdentity;
  /** Pre-formatted age, so locale handling stays with the caller. */
  ageLabel?: string;
  backHref: string;
  backLabel: string;
  tabs?: TabDef[];
  activeTab?: string;
  onTabChange?: (key: string) => void;
  actions?: ReactNode;
  /** A single status element - active admission, review needed, etc. */
  status?: ReactNode;
}) {
  const meta = [
    ageLabel,
    patient.sex,
    patient.date_of_birth ? `DOB ${patient.date_of_birth}` : null,
    patient.patient_identifier ? `ID ${patient.patient_identifier}` : null,
    patient.cnp ? `CNP ${patient.cnp}` : null,
  ].filter(Boolean) as string[];

  return (
    <div className="b-ctx">
      <div className="b-ctx-row">
        <Link
          href={backHref}
          className="b-btn b-btn-ghost b-btn-icon b-btn-sm"
          aria-label={backLabel}
          title={backLabel}
        >
          <IconChevronLeft size={16} />
        </Link>

        <div className="b-ctx-id">
          <span className="b-avatar" aria-hidden="true">
            {initials(patient.full_name)}
          </span>

          <div style={{ minWidth: 0 }}>
            <div className="b-ctx-name">{patient.full_name}</div>
            <div className="b-ctx-meta">
              {meta.map((entry, index) => (
                <span key={entry} style={{ display: "inline-flex", gap: 6 }}>
                  {index > 0 ? <span className="b-ctx-dot">·</span> : null}
                  {entry}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="b-ctx-actions">
          {status}
          {actions}
        </div>
      </div>

      {tabs?.length && activeTab && onTabChange ? (
        <div className="b-ctx-tabs">
          <Tabs
            tabs={tabs}
            activeTab={activeTab}
            onChange={onTabChange}
            ariaLabel={`${patient.full_name} record sections`}
          />
        </div>
      ) : null}
    </div>
  );
}
