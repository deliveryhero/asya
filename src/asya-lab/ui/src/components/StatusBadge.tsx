import { STATUS_COLORS } from "../tokens";
import type { ActorState } from "../types";

export function StatusBadge({ state }: { state: ActorState }) {
  const colors = STATUS_COLORS[state];
  return (
    <span
      role="status"
      aria-label={`Status: ${state}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 9999,
        fontSize: 12,
        fontFamily: "monospace",
        backgroundColor: colors?.bg || "#f9fafb",
        color: colors?.border || "#6b7280",
        border: `1px solid ${colors?.border || "#d1d5db"}`,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: colors?.border || "#6b7280",
        }}
      />
      {state}
    </span>
  );
}
