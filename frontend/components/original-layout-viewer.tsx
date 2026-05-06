"use client";

type LayoutBlock = {
  id: string;
  type: "paragraph" | "line" | string;
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
};

type LayoutPage = {
  page_number: number;
  width: number;
  height: number;
  paragraph_blocks?: LayoutBlock[];
  line_blocks?: LayoutBlock[];
};

type OriginalLayout = {
  provider?: string;
  plain_text?: string;
  pages?: LayoutPage[];
};

type OriginalLayoutViewerProps = {
  layout?: OriginalLayout | null;
  mode?: "lines" | "paragraphs";
};

function safePages(layout?: OriginalLayout | null) {
  if (!layout?.pages || !Array.isArray(layout.pages)) return [];
  return layout.pages.filter((page) => Number(page.width) > 0 && Number(page.height) > 0);
}

export default function OriginalLayoutViewer({ layout, mode = "lines" }: OriginalLayoutViewerProps) {
  const pages = safePages(layout);

  if (!pages.length) {
    return (
      <div
        className="soft-card-tight"
        style={{
          padding: 18,
          background: "var(--panel-2)",
          color: "var(--muted)",
          lineHeight: 1.6,
        }}
      >
        No original layout data was saved for this document yet. Re-upload or reprocess this document after Document AI
        layout extraction is enabled.
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gap: 24,
        minHeight: 0,
        overflow: "auto",
        padding: 12,
        background: "var(--panel-2)",
        borderRadius: 24,
        border: "1px solid var(--border)",
      }}
    >
      {pages.map((page) => {
        const blocks =
          mode === "paragraphs"
            ? page.paragraph_blocks || []
            : page.line_blocks?.length
            ? page.line_blocks
            : page.paragraph_blocks || [];

        return (
          <div
            key={page.page_number}
            style={{
              width: "min(100%, 980px)",
              aspectRatio: `${page.width} / ${page.height}`,
              position: "relative",
              margin: "0 auto",
              background: "#ffffff",
              color: "#111827",
              borderRadius: 10,
              border: "1px solid rgba(15, 23, 42, 0.16)",
              boxShadow: "0 20px 60px rgba(15, 23, 42, 0.12)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: 8,
                right: 10,
                fontSize: 10,
                fontWeight: 800,
                color: "#6b7280",
              }}
            >
              {page.page_number}
            </div>

            {blocks.map((block) => {
              const left = `${(block.x / page.width) * 100}%`;
              const top = `${(block.y / page.height) * 100}%`;
              const width = `${(block.w / page.width) * 100}%`;

              return (
                <div
                  key={block.id}
                  title={block.text}
                  style={{
                    position: "absolute",
                    left,
                    top,
                    width,
                    minHeight: `${Math.max((block.h / page.height) * 100, 0.4)}%`,
                    fontFamily: "Arial, Helvetica, sans-serif",
                    fontSize: mode === "paragraphs" ? "clamp(5px, 0.55vw, 11px)" : "clamp(5px, 0.5vw, 10px)",
                    lineHeight: 1.12,
                    fontWeight: 500,
                    whiteSpace: mode === "paragraphs" ? "pre-wrap" : "nowrap",
                    overflow: "visible",
                    color: "#111827",
                  }}
                >
                  {block.text}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}