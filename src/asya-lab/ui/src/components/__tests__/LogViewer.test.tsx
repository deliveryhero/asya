import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LogViewer } from "../LogViewer";

describe("LogViewer", () => {
  it("shows empty state", () => {
    render(<LogViewer lines={[]} />);
    expect(screen.getByText("No logs available")).toBeTruthy();
  });

  it("renders log lines", () => {
    const lines = [
      {
        timestamp: "12:00:00",
        actor: "test",
        level: "info" as const,
        message: "hello",
      },
    ];
    render(<LogViewer lines={lines} />);
    expect(screen.getByText("hello")).toBeTruthy();
  });
});
