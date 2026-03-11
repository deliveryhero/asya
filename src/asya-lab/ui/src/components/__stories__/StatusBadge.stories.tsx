import type { Meta, StoryObj } from "@storybook/react";
import { StatusBadge } from "../StatusBadge";

const meta = {
  title: "Components/StatusBadge",
  component: StatusBadge,
} satisfies Meta<typeof StatusBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Running: Story = { args: { state: "running" } };
export const Error: Story = { args: { state: "error" } };
export const Pending: Story = { args: { state: "pending" } };
export const ScaledToZero: Story = { args: { state: "scaled-to-zero" } };
export const Processing: Story = { args: { state: "processing" } };
