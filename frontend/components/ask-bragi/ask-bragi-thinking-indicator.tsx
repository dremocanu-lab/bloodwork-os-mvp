"use client";

/**
 * The one, shared Ask Bragi "thinking" indicator — used everywhere Ask
 * Bragi is waiting on a response (patient chat, doctor chat, Overview
 * surface, contextual panel, document-scoped chat). Never a generic
 * three-dot bounce, a browser spinner, or an AI-sparkle glyph — a small
 * abstract purple mark that slowly rotates and morphs between a few
 * restrained geometric forms (rounded diamond -> soft hexagon -> rounded
 * square -> back). Built with `styled-jsx` (the same scoped-animation
 * convention this codebase already uses — see the local `Spinner` in
 * `app/patients/[id]/upload/page.tsx` — not a new pattern).
 *
 * Respects `prefers-reduced-motion`: falls back to a static, gently
 * pulsing shape (opacity only, no rotation/morph).
 *
 * Accessible: the shape itself is `aria-hidden` (decorative); the
 * adjacent status text (`label` prop) carries the actual meaning and is
 * what a screen reader announces via the `role="status"` live region —
 * never chain-of-thought/raw tool payloads, only safe, generic phase
 * names (see AskBragiChat's status mapping).
 */

export function AskBragiThinkingIndicator({
  label,
  size = 18,
  showLabel = true,
}: {
  /** Safe, generic phase text — e.g. "Reviewing the record…",
   * "Checking laboratory results…". Never raw tool/model internals. */
  label?: string;
  size?: number;
  showLabel?: boolean;
}) {
  const text = label || "Bragi is checking your record…";

  return (
    <span role="status" aria-live="polite" className="ask-bragi-thinking">
      <span className="ask-bragi-thinking-shape" aria-hidden="true" />
      {showLabel ? <span className="muted-text ask-bragi-thinking-label">{text}</span> : <span className="sr-only">{text}</span>}

      <style jsx>{`
        .ask-bragi-thinking {
          display: inline-flex;
          align-items: center;
          gap: var(--s2, 8px);
        }
        .ask-bragi-thinking-shape {
          display: inline-block;
          flex-shrink: 0;
          width: ${size}px;
          height: ${size}px;
          background: linear-gradient(135deg, var(--brand-500, #6d5dfc), var(--brand-600, #5544e8));
          animation: askBragiMorph 2.4s ease-in-out infinite;
          will-change: border-radius, transform;
        }
        .ask-bragi-thinking-label {
          font-size: var(--fs-caption, 13px);
        }

        @keyframes askBragiMorph {
          0% {
            border-radius: 42% 58% 60% 40% / 48% 42% 58% 52%;
            transform: rotate(0deg) scale(1);
          }
          25% {
            border-radius: 30% 30% 30% 30% / 30% 30% 30% 30%;
            transform: rotate(90deg) scale(0.94);
          }
          50% {
            border-radius: 16% 16% 16% 16% / 16% 16% 16% 16%;
            transform: rotate(180deg) scale(1.04);
          }
          75% {
            border-radius: 58% 42% 40% 60% / 52% 58% 42% 48%;
            transform: rotate(270deg) scale(0.97);
          }
          100% {
            border-radius: 42% 58% 60% 40% / 48% 42% 58% 52%;
            transform: rotate(360deg) scale(1);
          }
        }

        @media (prefers-reduced-motion: reduce) {
          .ask-bragi-thinking-shape {
            animation: askBragiPulseStatic 2.4s ease-in-out infinite;
            border-radius: 32%;
            transform: none;
          }
        }

        @keyframes askBragiPulseStatic {
          0%,
          100% {
            opacity: 0.65;
          }
          50% {
            opacity: 1;
          }
        }
      `}</style>
    </span>
  );
}
