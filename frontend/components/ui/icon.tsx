/**
 * Bragi icon set.
 *
 * One stroke weight, one grid, one visual voice. Replaces the mix of text
 * arrows ("↑", "›"), emoji and ad-hoc glyphs that were scattered across
 * pages. Icons are decorative by default (aria-hidden) - the adjacent label
 * carries the meaning. Pass a `title` only when an icon stands alone.
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & {
  size?: number;
  title?: string;
};

function Svg({ size = 15, title, children, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

/* --- navigation ------------------------------------------------------- */

export const IconHome = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V20h14V9.5" />
  </Svg>
);

export const IconUsers = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3 20c0-3.2 2.7-5.2 6-5.2s6 2 6 5.2" />
    <path d="M16.5 5.4a3.2 3.2 0 0 1 0 5.2M17.5 14.9c2.1.5 3.5 2.2 3.5 5.1" />
  </Svg>
);

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10.5" cy="10.5" r="6.5" />
    <path d="m15.5 15.5 4.5 4.5" />
  </Svg>
);

export const IconTimeline = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3v18" />
    <circle cx="6" cy="7.5" r="1.8" />
    <circle cx="6" cy="16.5" r="1.8" />
    <path d="M10.5 7.5h9M10.5 16.5h6" />
  </Svg>
);

export const IconLab = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 3h6M10 3v6.2L5.6 17A3 3 0 0 0 8.2 21h7.6a3 3 0 0 0 2.6-4L14 9.2V3" />
    <path d="M7.4 14h9.2" />
  </Svg>
);

export const IconDocument = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 13h6M9 17h4" />
  </Svg>
);

export const IconPill = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.6" y="8.6" width="18.8" height="6.8" rx="3.4" transform="rotate(-45 12 12)" />
    <path d="M9.2 9.2l5.6 5.6" />
  </Svg>
);

export const IconChart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20V4M4 20h16" />
    <path d="M8 16v-4M12 16V8M16 16v-6" />
  </Svg>
);

export const IconShield = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 21c4.6-1.8 7-5 7-9.4V5.6L12 3 5 5.6v6c0 4.4 2.4 7.6 7 9.4Z" />
    <path d="m9.2 12 2 2 3.6-3.8" />
  </Svg>
);

export const IconSettings = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="2.8" />
    <path d="M19.4 14.4a7.8 7.8 0 0 0 0-4.8l1.5-1.2-1.8-3.1-1.8.7a7.8 7.8 0 0 0-4.2-2.4L12.7 2h-3.6l-.4 1.9a7.8 7.8 0 0 0-4.2 2.4l-1.8-.7L.9 8.7l1.5 1.2a7.8 7.8 0 0 0 0 4.8L.9 15.9 2.7 19l1.8-.7a7.8 7.8 0 0 0 4.2 2.4l.4 1.9h3.6l.4-1.9a7.8 7.8 0 0 0 4.2-2.4l1.8.7 1.8-3.1z" />
  </Svg>
);

export const IconUpload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 16V4" />
    <path d="m7.5 8.5L12 4l4.5 4.5" />
    <path d="M4 16v2.5A2.5 2.5 0 0 0 6.5 21h11A2.5 2.5 0 0 0 20 18.5V16" />
  </Svg>
);

export const IconClipboard = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 4H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2" />
    <rect x="9" y="2.4" width="6" height="3.4" rx="1.2" />
    <path d="M9 12h6M9 16h4" />
  </Svg>
);

export const IconList = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 6h12M8 12h12M8 18h12" />
    <path d="M4 6h.01M4 12h.01M4 18h.01" />
  </Svg>
);

export const IconAlert = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4.5 2.8 20h18.4z" />
    <path d="M12 10v4M12 17h.01" />
  </Svg>
);

export const IconHospital = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 21V7l8-4 8 4v14" />
    <path d="M12 8.5v5M9.5 11h5" />
    <path d="M9 21v-4h6v4" />
  </Svg>
);

export const IconHeart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20s-7.5-4.6-7.5-9.6A4.4 4.4 0 0 1 12 7.6a4.4 4.4 0 0 1 7.5 2.8C19.5 15.4 12 20 12 20Z" />
  </Svg>
);

/* --- controls --------------------------------------------------------- */

export const IconMenu = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 6.5h17M3.5 12h17M3.5 17.5h17" />
  </Svg>
);

export const IconClose = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Svg>
);

export const IconChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="m9.5 5.5 6.5 6.5-6.5 6.5" />
  </Svg>
);

export const IconChevronLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14.5 5.5 8 12l6.5 6.5" />
  </Svg>
);

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="m5.5 9.5 6.5 6.5 6.5-6.5" />
  </Svg>
);

export const IconChevronUpDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="m8 10 4-4 4 4M8 14l4 4 4-4" />
  </Svg>
);

export const IconMore = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="5.5" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="12" cy="18.5" r="1.4" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconFilter = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 6h17M6.5 12h11M10 18h4" />
  </Svg>
);

export const IconPlus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="m4.5 12.5 5 5 10-11" />
  </Svg>
);

export const IconExternal = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 4h6v6M20 4l-8.5 8.5" />
    <path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />
  </Svg>
);

export const IconArrowUp = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </Svg>
);

export const IconArrowDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M6 13l6 6 6-6" />
  </Svg>
);

export const IconLogout = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" />
    <path d="M15.5 8.5 19 12l-3.5 3.5M9 12h10" />
  </Svg>
);

export const IconGlobe = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3.4 9.5h17.2M3.4 14.5h17.2" />
    <path d="M12 3c-2.4 2.4-3.6 5.4-3.6 9s1.2 6.6 3.6 9c2.4-2.4 3.6-5.4 3.6-9S14.4 5.4 12 3Z" />
  </Svg>
);

export const IconSun = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.4 5.4l1.4 1.4M17.2 17.2l1.4 1.4M18.6 5.4l-1.4 1.4M6.8 17.2l-1.4 1.4" />
  </Svg>
);

export const IconMoon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
  </Svg>
);

export const IconInbox = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 13h5l1.4 2.6h5.2L16 13h5" />
    <path d="M3 13 5.6 5.4A2 2 0 0 1 7.5 4h9a2 2 0 0 1 1.9 1.4L21 13v4.5A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5z" />
  </Svg>
);

export const IconKey = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="4.2" />
    <path d="m11 11 8 8M16.5 16.5 15 18M19 14l-1.6 1.6" />
  </Svg>
);
