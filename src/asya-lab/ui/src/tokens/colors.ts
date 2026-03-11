export const STATUS_COLORS = {
  running: { border: "var(--asya-status-running-border, #22c55e)", bg: "var(--asya-status-running-bg, #f0fdf4)" },
  "scaled-to-zero": { border: "var(--asya-status-idle-border, #9ca3af)", bg: "var(--asya-status-idle-bg, #f9fafb)" },
  error: { border: "var(--asya-status-error-border, #ef4444)", bg: "var(--asya-status-error-bg, #fef2f2)" },
  processing: { border: "var(--asya-status-processing-border, #3b82f6)", bg: "var(--asya-status-processing-bg, #eff6ff)" },
  pending: { border: "var(--asya-status-pending-border, #eab308)", bg: "var(--asya-status-pending-bg, #fefce8)" },
} as const;

export const TYPE_COLORS = {
  router: "var(--asya-type-router, #fefce8)",
  actor: "var(--asya-type-actor, #eff6ff)",
} as const;

export const LOG_COLORS = {
  debug: "var(--asya-log-debug, #9ca3af)",
  info: "var(--asya-log-info, #3b82f6)",
  warn: "var(--asya-log-warn, #eab308)",
  error: "var(--asya-log-error, #ef4444)",
} as const;

export const EDGE_COLORS = {
  sequential: "#000000",
  true: "#16a34a",
  false: "#dc2626",
  except: "#9ca3af",
  fanout: "#9333ea",
} as const;
