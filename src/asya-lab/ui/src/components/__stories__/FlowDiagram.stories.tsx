import type { Meta, StoryObj } from "@storybook/react";
import { FlowDiagram } from "../FlowDiagram";
import type { FlowGraph } from "../../types";

const meta = {
  title: "Components/FlowDiagram",
  component: FlowDiagram,
} satisfies Meta<typeof FlowDiagram>;

export default meta;
type Story = StoryObj<typeof meta>;

const SIMPLE_GRAPH: FlowGraph = {
  flow: "order-processing",
  nodes: [
    {
      id: "start",
      type: "router",
      role: "mutation",
      label: "initialize",
      entrypoint: true,
      mutations: ["p['status'] = 'processing'"],
    },
    {
      id: "validate",
      type: "actor",
      role: "processor",
      label: "validate_order",
      handler: "handlers.validate",
    },
    {
      id: "cond",
      type: "router",
      role: "conditional",
      label: "order type check",
      condition: "p['type'] == 'express'",
    },
    { id: "express", type: "actor", role: "processor", label: "express_handler" },
    {
      id: "standard",
      type: "actor",
      role: "processor",
      label: "standard_handler",
    },
    {
      id: "payment",
      type: "actor",
      role: "processor",
      label: "payment_processor",
      exitpoint: true,
    },
  ],
  edges: [
    { source: "start", target: "validate", type: "sequential" },
    { source: "validate", target: "cond", type: "sequential" },
    { source: "cond", target: "express", type: "true" },
    { source: "cond", target: "standard", type: "false" },
    { source: "express", target: "payment", type: "sequential" },
    { source: "standard", target: "payment", type: "sequential" },
  ],
  groups: [],
};

export const Default: Story = {
  args: { graph: SIMPLE_GRAPH },
};

export const WithStatus: Story = {
  args: {
    graph: SIMPLE_GRAPH,
    getActorStatus: (name: string) =>
      name === "validate"
        ? {
            replicas: 3,
            desiredReplicas: 3,
            queueDepth: 12,
            state: "running",
          }
        : name === "express"
          ? {
              replicas: 0,
              desiredReplicas: 0,
              queueDepth: 0,
              state: "scaled-to-zero",
            }
          : null,
  },
};
