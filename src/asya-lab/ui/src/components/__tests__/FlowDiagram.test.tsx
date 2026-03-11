import { describe, it, expect, beforeAll } from "vitest";
import { render } from "@testing-library/react";
import { FlowDiagram } from "../FlowDiagram";
import type { FlowGraph } from "../../types";

beforeAll(() => {
  // React Flow requires ResizeObserver in jsdom
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const SIMPLE_GRAPH: FlowGraph = {
  flow: "test",
  nodes: [
    {
      id: "start",
      type: "router",
      role: "mutation",
      label: "start",
      entrypoint: true,
    },
    { id: "actor_a", type: "actor", role: "processor", label: "actor_a" },
  ],
  edges: [{ source: "start", target: "actor_a", type: "sequential" }],
  groups: [],
};

describe("FlowDiagram", () => {
  it("renders without crashing", () => {
    const { container } = render(<FlowDiagram graph={SIMPLE_GRAPH} />);
    expect(container.querySelector(".flow-diagram")).toBeTruthy();
  });
});
