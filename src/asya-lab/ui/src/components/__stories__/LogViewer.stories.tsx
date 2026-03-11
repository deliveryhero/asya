import type { Meta, StoryObj } from "@storybook/react";
import { LogViewer } from "../LogViewer";

const meta = {
  title: "Components/LogViewer",
  component: LogViewer,
} satisfies Meta<typeof LogViewer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = { args: { lines: [] } };
export const WithLogs: Story = {
  args: {
    lines: [
      {
        timestamp: "12:00:01",
        actor: "validate",
        level: "info",
        message: "Processing order #123",
      },
      {
        timestamp: "12:00:02",
        actor: "validate",
        level: "debug",
        message: "Checking inventory",
      },
      {
        timestamp: "12:00:03",
        actor: "express",
        level: "warn",
        message: "Queue depth high",
      },
      {
        timestamp: "12:00:04",
        actor: "payment",
        level: "error",
        message: "Payment gateway timeout",
      },
    ],
  },
};
