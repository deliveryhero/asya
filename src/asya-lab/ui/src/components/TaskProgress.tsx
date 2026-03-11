import { STATUS_COLORS } from "../tokens";
import type { TaskProgress as TaskProgressType } from "../types";

export function TaskProgress({ progress }: { progress: TaskProgressType }) {
  return (
    <div style={{ fontFamily: "monospace", fontSize: 12 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 4,
        }}
      >
        <span>Task {progress.id}</span>
        <span>{progress.status}</span>
      </div>
      <div
        style={{
          height: 8,
          backgroundColor: "#e5e7eb",
          borderRadius: 4,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${progress.progressPercent}%`,
            height: "100%",
            backgroundColor: STATUS_COLORS.processing.border,
            transition: "width 0.3s ease",
          }}
        />
      </div>
      <div style={{ color: "#6b7280", marginTop: 4 }}>
        {progress.currentActor} ({progress.actorsCompleted}/
        {progress.totalActors})
        {progress.message && ` - ${progress.message}`}
      </div>
    </div>
  );
}
