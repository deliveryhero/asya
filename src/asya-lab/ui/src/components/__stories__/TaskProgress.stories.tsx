import type { Meta, StoryObj } from "@storybook/react";
import { TaskProgress } from "../TaskProgress";

const meta = {
  title: "Components/TaskProgress",
  component: TaskProgress,
} satisfies Meta<typeof TaskProgress>;

export default meta;
type Story = StoryObj<typeof meta>;

export const InProgress: Story = {
  args: {
    progress: {
      id: "task-123",
      status: "working",
      progressPercent: 60,
      currentActor: "validate",
      actorsCompleted: 3,
      totalActors: 5,
      message: "Validating order",
    },
  },
};

export const Complete: Story = {
  args: {
    progress: {
      id: "task-456",
      status: "completed",
      progressPercent: 100,
      currentActor: "payment",
      actorsCompleted: 5,
      totalActors: 5,
      message: "Done",
    },
  },
};
