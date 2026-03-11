import { useRef, useEffect } from "react";
import { LOG_COLORS } from "../tokens";
import type { LogLine } from "../types";

export interface LogViewerProps {
  lines: LogLine[];
  maxLines?: number;
}

export function LogViewer({ lines, maxLines = 200 }: LogViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines]);

  const visible = lines.slice(-maxLines);

  return (
    <div
      ref={containerRef}
      role="log"
      aria-label="Actor log output"
      aria-live="polite"
      style={{
        fontFamily: "monospace",
        fontSize: 12,
        lineHeight: 1.6,
        overflow: "auto",
        maxHeight: 400,
        backgroundColor: "#1e1e1e",
        color: "#d4d4d4",
        padding: 8,
        borderRadius: 4,
      }}
    >
      {visible.length === 0 && (
        <div style={{ color: "#6b7280" }}>No logs available</div>
      )}
      {visible.map((line, i) => (
        <div key={i}>
          <span style={{ color: "#6b7280" }}>{line.timestamp} </span>
          <span style={{ color: LOG_COLORS[line.level] }}>[{line.level}]</span>{" "}
          <span style={{ color: "#93c5fd" }}>{line.actor}</span>{" "}
          <span>{line.message}</span>
        </div>
      ))}
    </div>
  );
}
