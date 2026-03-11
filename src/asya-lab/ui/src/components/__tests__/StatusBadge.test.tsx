import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("renders state text", () => {
    render(<StatusBadge state="running" />);
    expect(screen.getByText("running")).toBeTruthy();
  });

  it("renders error state", () => {
    render(<StatusBadge state="error" />);
    expect(screen.getByText("error")).toBeTruthy();
  });
});
