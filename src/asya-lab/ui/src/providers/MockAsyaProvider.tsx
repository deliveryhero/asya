import type { ReactNode } from "react";
import { AsyaContext } from "./AsyaContext";
import type { AsyaContextValue } from "../types";

const DEFAULT_MOCK: AsyaContextValue = {
  actors: [],
  getActorStatus: () => null,
  subscribeLogs: () => () => {},
  logLines: [],
  taskProgress: null,
  subscribeTask: () => () => {},
  flowName: "mock-flow",
  context: "local",
  readonly: true,
  connectionState: "connected",
};

export function MockAsyaProvider({
  children,
  overrides = {},
}: {
  children: ReactNode;
  overrides?: Partial<AsyaContextValue>;
}) {
  return (
    <AsyaContext.Provider value={{ ...DEFAULT_MOCK, ...overrides }}>
      {children}
    </AsyaContext.Provider>
  );
}
