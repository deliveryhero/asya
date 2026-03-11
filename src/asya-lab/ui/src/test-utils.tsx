import type { ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { MockAsyaProvider } from "./providers";
import type { AsyaContextValue } from "./types";

export function renderWithProvider(
  ui: ReactNode,
  overrides: Partial<AsyaContextValue> = {},
  options?: RenderOptions,
) {
  return render(
    <MockAsyaProvider overrides={overrides}>{ui}</MockAsyaProvider>,
    options,
  );
}
