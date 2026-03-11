import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { STATUS_COLORS, TYPE_COLORS } from "../tokens";
import type { ActorStatus } from "../types";
import "./ActorNode.css";

export interface ActorNodeData {
  label: string;
  nodeType: "router" | "actor";
  role: string;
  handler?: string;
  entrypoint?: boolean;
  exitpoint?: boolean;
  status?: ActorStatus;
  condition?: string;
  mutations?: string[];
}

const ROLE_BADGES: Record<string, string> = {
  conditional: "C",
  mutation: "M",
  loop: "L",
  fanout: "F",
  fanin: "A",
  processor: "P",
  raise_exit: "X",
};

function ActorNodeComponent({ data }: NodeProps) {
  const d = data as unknown as ActorNodeData;
  const bgColor = TYPE_COLORS[d.nodeType] || TYPE_COLORS.actor;
  const borderWidth = d.entrypoint || d.exitpoint ? 3 : 1;
  const borderColor = d.status
    ? STATUS_COLORS[d.status.state]?.border || "#d1d5db"
    : "#d1d5db";

  return (
    <div
      className="actor-node"
      role="treeitem"
      aria-label={`${d.nodeType} ${d.label}, role: ${d.role}${d.status ? `, state: ${d.status.state}` : ""}`}
      style={{
        backgroundColor: bgColor,
        borderWidth,
        borderColor,
        borderStyle: "solid",
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="actor-node__header">
        <span className="actor-node__name">{d.label}</span>
        <span className="actor-node__badge" aria-label={`role: ${d.role}`}>
          {ROLE_BADGES[d.role] || "?"}
        </span>
      </div>
      {d.handler && <div className="actor-node__handler">{d.handler}</div>}
      {d.condition && (
        <div className="actor-node__condition">if {d.condition}</div>
      )}
      {d.status && (
        <div className="actor-node__status">
          replicas: {d.status.replicas}/{d.status.desiredReplicas} queue:{" "}
          {d.status.queueDepth}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export const ActorNode = memo(ActorNodeComponent);
