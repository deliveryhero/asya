import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  type Node,
  type Edge,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { computeLayout, NODE_WIDTH, NODE_HEIGHT } from "./layout";
import { ActorNode, type ActorNodeData } from "./ActorNode";
import { EDGE_COLORS } from "../tokens";
import type { FlowGraph, ActorStatus } from "../types";
import "./FlowDiagram.css";

const nodeTypes = { actorNode: ActorNode };

export interface FlowDiagramProps {
  graph: FlowGraph;
  getActorStatus?: (name: string) => ActorStatus | null;
  onNodeClick?: (nodeId: string) => void;
}

export function FlowDiagram({
  graph,
  getActorStatus,
  onNodeClick,
}: FlowDiagramProps) {
  const { nodes, edges } = useMemo(() => {
    const layout = computeLayout(graph.nodes, graph.edges);

    const rfNodes: Node[] = graph.nodes.map((gn) => {
      const pos = layout.nodes.find((p) => p.id === gn.id);
      const data: ActorNodeData = {
        label: gn.label,
        nodeType: gn.type,
        role: gn.role,
        handler: gn.handler,
        entrypoint: gn.entrypoint,
        exitpoint: gn.exitpoint,
        status: getActorStatus?.(gn.id) ?? undefined,
        condition: gn.condition,
        mutations: gn.mutations,
      };
      return {
        id: gn.id,
        type: "actorNode",
        position: { x: pos?.x ?? 0, y: pos?.y ?? 0 },
        data: { ...data } as Record<string, unknown>,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
      };
    });

    const rfEdges: Edge[] = graph.edges.map((ge, i) => ({
      id: `e-${i}`,
      source: ge.source,
      target: ge.target,
      label:
        ge.label ||
        (ge.type === "true"
          ? "TRUE"
          : ge.type === "false"
            ? "FALSE"
            : undefined),
      style: {
        stroke: EDGE_COLORS[ge.type] || EDGE_COLORS.sequential,
        strokeDasharray: ge.type === "except" ? "5,5" : undefined,
      },
      labelStyle: {
        fill: EDGE_COLORS[ge.type] || EDGE_COLORS.sequential,
        fontSize: 10,
        fontFamily: "monospace",
      },
    }));

    return { nodes: rfNodes, edges: rfEdges };
  }, [graph, getActorStatus]);

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick],
  );

  return (
    <div className="flow-diagram">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        minZoom={0.1}
        maxZoom={2}
      >
        <Controls />
        <MiniMap />
        <Background />
      </ReactFlow>
    </div>
  );
}
