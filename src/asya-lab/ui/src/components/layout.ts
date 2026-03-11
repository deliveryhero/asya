import dagre from "dagre";
import type { GraphNode, GraphEdge } from "../types";

const NODE_WIDTH = 280;
const NODE_HEIGHT = 80;

export interface LayoutResult {
  nodes: Array<{ id: string; x: number; y: number }>;
  edges: GraphEdge[];
}

export function computeLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
): LayoutResult {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", ranksep: 60, nodesep: 40 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  return {
    nodes: nodes.map((n) => {
      const pos = g.node(n.id);
      return {
        id: n.id,
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      };
    }),
    edges,
  };
}

export { NODE_WIDTH, NODE_HEIGHT };
