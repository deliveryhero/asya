import { useAsya } from "../providers/AsyaContext";
import { StatusBadge } from "./StatusBadge";
import { LogViewer } from "./LogViewer";
import type { GraphNode } from "../types";

export interface ActorDetailProps {
  node: GraphNode;
  onClose?: () => void;
}

export function ActorDetail({ node, onClose }: ActorDetailProps) {
  const { getActorStatus, logLines } = useAsya();
  const status = getActorStatus(node.id);
  const actorLogs = logLines.filter((l) => l.actor === node.id);

  return (
    <div
      style={{
        fontFamily: "monospace",
        fontSize: 12,
        padding: 16,
        borderLeft: "1px solid #e5e7eb",
        minWidth: 320,
        overflow: "auto",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <h3 style={{ margin: 0 }}>{node.label}</h3>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close detail panel"
            style={{ cursor: "pointer", border: "none", background: "none" }}
          >
            x
          </button>
        )}
      </div>

      <div style={{ marginBottom: 12 }}>
        <div>
          <strong>Type:</strong> {node.type}
        </div>
        <div>
          <strong>Role:</strong> {node.role}
        </div>
        {node.handler && (
          <div>
            <strong>Handler:</strong> {node.handler}
          </div>
        )}
        {node.image && (
          <div>
            <strong>Image:</strong> {node.image}
          </div>
        )}
      </div>

      {status && (
        <div style={{ marginBottom: 12 }}>
          <h4 style={{ margin: "0 0 4px" }}>Status</h4>
          <StatusBadge state={status.state} />
          <div style={{ marginTop: 4 }}>
            Replicas: {status.replicas}/{status.desiredReplicas}
          </div>
          <div>Queue depth: {status.queueDepth}</div>
          {status.lastError && (
            <div style={{ color: "#ef4444" }}>Error: {status.lastError}</div>
          )}
        </div>
      )}

      <div>
        <h4 style={{ margin: "0 0 4px" }}>Logs</h4>
        <LogViewer lines={actorLogs} />
      </div>
    </div>
  );
}
