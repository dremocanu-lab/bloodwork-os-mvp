"use client";

import { useEffect, useState } from "react";

function useDarkMode() {
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const el = document.documentElement;
    const update = () => setIsDark(el.classList.contains("dark"));
    update();
    const observer = new MutationObserver(update);
    observer.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}

type BragiLogoProps = {
  height?: number;
  showText?: boolean;
};

export default function BragiLogo({ height = 64, showText = true }: BragiLogoProps) {
  const isDark = useDarkMode();

  const shieldColor = isDark ? "#FFFFFF" : "#82C09A";
  const crossColor = isDark ? "#0f1b2d" : "#FFFFFF";
  const textColor = shieldColor;

  const viewH = showText ? 96 : 68;
  const viewW = 100;
  const svgWidth = Math.round(height * (viewW / viewH));

  return (
    <svg
      viewBox={`0 0 ${viewW} ${viewH}`}
      width={svgWidth}
      height={height}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ display: "block", flexShrink: 0 }}
    >
      {/* Shield */}
      <path
        d="M28 4 L72 4 Q78 4 78 10 L78 42 Q78 58 50 66 Q22 58 22 42 L22 10 Q22 4 28 4 Z"
        fill={shieldColor}
      />
      {/* Cross — horizontal bar */}
      <rect x="34" y="32" width="32" height="6" rx="3" fill={crossColor} />
      {/* Cross — vertical bar */}
      <rect x="47" y="19" width="6" height="32" rx="3" fill={crossColor} />
      {/* Wordmark */}
      {showText && (
        <text
          x="50"
          y="90"
          textAnchor="middle"
          fontSize="20"
          fontWeight="700"
          fontFamily="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
          letterSpacing="-0.5"
          fill={textColor}
        >
          bragi
        </text>
      )}
    </svg>
  );
}
