/**
 * Bragi navigation model.
 *
 * A single source of truth for every role's navigation, consumed by the
 * desktop sidebar, the mobile bottom bar and the mobile menu sheet. Before
 * this, each surface hard-coded its own list, which is how the roles drifted
 * into feeling like different applications.
 *
 * `primary: true` marks the destinations that appear in the mobile bottom bar
 * (at most four, plus a "More" entry). Everything else stays reachable from
 * the sheet, so nothing is hidden - only re-ranked for the viewport.
 */

import type { ComponentType, SVGProps } from "react";
import {
  IconChart,
  IconChat,
  IconClipboard,
  IconDocument,
  IconHeart,
  IconHome,
  IconHospital,
  IconInbox,
  IconKey,
  IconLab,
  IconList,
  IconPill,
  IconSearch,
  IconSettings,
  IconShield,
  IconTimeline,
  IconUpload,
  IconUsers,
} from "@/components/ui/icon";

// Ask Bragi is feature-flagged off in production (ASK_BRAGI_ENABLED,
// backend-side) — this nav entry mirrors that with its own explicit
// opt-in so it never appears as a dead link for real users before the
// feature is actually turned on. See BRAGI_ASK_BRAGI_PLAN.md's "Feature
// flags" section.
const ASK_BRAGI_NAV_ENABLED = process.env.NEXT_PUBLIC_ASK_BRAGI_ENABLED === "true";

export type Role = "patient" | "doctor" | "admin" | "care_partner";

export type NavUser = {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  department?: string | null;
  hospital_name?: string | null;
  doctor_type?: "pcp" | "specialist" | null;
};

export type NavItem = {
  key: string;
  label: string;
  href: string;
  icon: ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;
  /** Shown in the mobile bottom bar. */
  primary?: boolean;
  /** Matches child routes too (e.g. /my-records matches /my-records/x). */
  exact?: boolean;
};

export type NavGroup = {
  key: string;
  /** Group heading; omit for the first, unlabelled group. */
  label?: string;
  items: NavItem[];
};

type T = (key: string) => string;

/** Where each role lands after signing in. */
export function getHomeHref(user: Pick<NavUser, "role" | "doctor_type">): string {
  if (user.role === "patient") return "/my-records";
  if (user.role === "doctor") {
    return user.doctor_type === "pcp" ? "/pcp/workspace" : "/my-patients";
  }
  if (user.role === "care_partner") return "/care-partner";
  return "/assignments";
}

/** Human label for the workspace a user is currently in. */
export function getWorkspaceLabel(user: Pick<NavUser, "role" | "doctor_type">, t: T): string {
  if (user.role === "doctor") {
    return user.doctor_type === "pcp" ? t("pcpWorkspace") : t("doctorWorkspace");
  }
  if (user.role === "admin") return t("adminWorkspace");
  if (user.role === "care_partner") return t("carePartnerWorkspace");
  return t("patientPortal");
}

/** The organisation line under the workspace label, where one applies. */
export function getOrgLabel(user: NavUser, t: T): string | null {
  if (user.role === "doctor" || user.role === "admin") {
    const parts = [user.department, user.hospital_name].filter(Boolean);
    return parts.length ? parts.join(" · ") : t("hospital");
  }
  return null;
}

export function getNavGroups(user: NavUser, t: T): NavGroup[] {
  const isPCP = user.role === "doctor" && user.doctor_type === "pcp";

  if (user.role === "doctor") {
    return [
      {
        key: "care",
        items: [
          ...(isPCP
            ? [
                {
                  key: "pcp",
                  label: t("pcpWorkspace"),
                  href: "/pcp/workspace",
                  icon: IconHome,
                  primary: true,
                },
              ]
            : []),
          {
            key: "patients",
            label: t("myCurrentPatients"),
            href: "/my-patients",
            icon: IconUsers,
            primary: true,
          },
          {
            key: "search",
            label: t("searchPatients"),
            href: "/patients/search",
            icon: IconSearch,
            primary: true,
          },
        ],
      },
    ];
  }

  if (user.role === "patient") {
    return [
      {
        key: "record",
        label: t("navMyRecord"),
        items: [
          {
            key: "records",
            label: t("navOverview"),
            href: "/my-records",
            icon: IconHome,
            primary: true,
            exact: true,
          },
          {
            key: "timeline",
            label: t("navTimeline"),
            href: "/my-records/timeline",
            icon: IconTimeline,
            primary: true,
          },
          {
            key: "medications",
            label: t("navMedications"),
            href: "/my-records/medications",
            icon: IconPill,
            primary: true,
          },
          ...(ASK_BRAGI_NAV_ENABLED
            ? [
                {
                  key: "ask-bragi",
                  label: "Ask Bragi",
                  href: "/ask-bragi",
                  icon: IconChat,
                },
              ]
            : []),
          {
            key: "upload",
            label: t("uploadDocuments"),
            href: "/my-records/upload",
            icon: IconUpload,
          },
        ],
      },
      {
        key: "account",
        label: t("navAccount"),
        items: [
          {
            key: "access",
            label: t("myAccess"),
            href: "/my-records/access",
            icon: IconShield,
          },
          {
            key: "settings",
            label: t("patientSettings"),
            href: "/my-records/settings",
            icon: IconSettings,
          },
        ],
      },
    ];
  }

  if (user.role === "admin") {
    return [
      {
        key: "operations",
        label: t("navOperations"),
        items: [
          {
            key: "assignments",
            label: t("assignPatients"),
            href: "/assignments",
            icon: IconInbox,
            primary: true,
          },
          {
            key: "doctors",
            label: t("adminDoctorsNav"),
            href: "/admin/doctors",
            icon: IconUsers,
            primary: true,
          },
        ],
      },
      {
        key: "quality",
        label: t("navQuality"),
        items: [
          {
            key: "analytes",
            label: t("navAnalyteGaps"),
            href: "/admin/analytes",
            icon: IconLab,
            primary: true,
          },
          {
            key: "logs",
            label: t("navAuditLog"),
            href: "/admin/logs",
            icon: IconList,
          },
        ],
      },
    ];
  }

  // care_partner
  return [
    {
      key: "shared",
      items: [
        {
          key: "home",
          label: t("navOverview"),
          href: "/care-partner",
          icon: IconHome,
          primary: true,
          exact: true,
        },
        {
          key: "shared",
          label: t("sharedWithMe"),
          href: "/care-partner/shared",
          icon: IconDocument,
          primary: true,
        },
        {
          key: "dependants",
          label: t("myDependants"),
          href: "/care-partner/dependants",
          icon: IconHeart,
          primary: true,
        },
        {
          key: "upload",
          label: t("uploadDocuments"),
          href: "/care-partner/upload",
          icon: IconUpload,
        },
      ],
    },
  ];
}

/** Flatten groups into the ordered list of items. */
export function flattenNav(groups: NavGroup[]): NavItem[] {
  return groups.flatMap((g) => g.items);
}

/**
 * Which nav item owns the current pathname. Longest matching href wins, so
 * /my-records/timeline highlights Timeline rather than Overview.
 */
export function activeNavKey(items: NavItem[], pathname: string): string | null {
  let best: NavItem | null = null;

  for (const item of items) {
    const matches = item.exact
      ? pathname === item.href
      : pathname === item.href || pathname.startsWith(`${item.href}/`);

    if (matches && (!best || item.href.length > best.href.length)) {
      best = item;
    }
  }

  return best?.key ?? null;
}

/** The clinical workspace tabs shown when a patient record is open. */
export type WorkspaceTab = {
  key: string;
  label: string;
  href: (patientId: string | number) => string;
  icon: ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;
};

export const DOCTOR_WORKSPACE_TABS: WorkspaceTab[] = [
  { key: "overview", label: "navOverview", href: (id) => `/patients/${id}`, icon: IconHome },
  { key: "timeline", label: "navTimeline", href: (id) => `/patients/${id}/timeline`, icon: IconTimeline },
  { key: "labs", label: "navLabs", href: (id) => `/patients/${id}?tab=labs`, icon: IconLab },
  { key: "documents", label: "navDocuments", href: (id) => `/patients/${id}?tab=documents`, icon: IconDocument },
  {
    key: "medications",
    label: "navMedications",
    href: (id) => `/patients/${id}/medications/list`,
    icon: IconPill,
  },
  { key: "analytics", label: "navAnalytics", href: (id) => `/patients/${id}/analytics`, icon: IconChart },
  {
    key: "admissions",
    label: "navAdmissions",
    href: (id) => `/patients/${id}/hospitalizations`,
    icon: IconHospital,
  },
];

export const PATIENT_WORKSPACE_TABS: WorkspaceTab[] = [
  { key: "overview", label: "navOverview", href: () => "/my-records", icon: IconHome },
  { key: "timeline", label: "navTimeline", href: () => "/my-records/timeline", icon: IconTimeline },
  { key: "medications", label: "navMedications", href: () => "/my-records/medications", icon: IconPill },
  { key: "access", label: "myAccess", href: () => "/my-records/access", icon: IconKey },
];

/** Quick actions offered on a patient record, by role. */
export const PATIENT_ACTIONS = {
  upload: (id: string | number) => `/patients/${id}/upload`,
  note: (id: string | number) => `/patients/${id}/notes/new`,
  assign: (id: string | number) => `/patients/${id}/assign`,
} as const;

export { IconClipboard };
