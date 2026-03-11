import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { useAsya } from "../AsyaContext";
import { MockAsyaProvider } from "../MockAsyaProvider";

describe("useAsya", () => {
  it("throws when used outside provider", () => {
    expect(() => {
      renderHook(() => useAsya());
    }).toThrow("useAsya() must be used within an AsyaProvider");
  });

  it("returns context value when inside provider", () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MockAsyaProvider>{children}</MockAsyaProvider>
    );
    const { result } = renderHook(() => useAsya(), { wrapper });
    expect(result.current.flowName).toBe("mock-flow");
    expect(result.current.connectionState).toBe("connected");
  });

  it("accepts overrides", () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MockAsyaProvider overrides={{ flowName: "custom" }}>
        {children}
      </MockAsyaProvider>
    );
    const { result } = renderHook(() => useAsya(), { wrapper });
    expect(result.current.flowName).toBe("custom");
  });
});
