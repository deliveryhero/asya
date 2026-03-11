import { createContext, useContext } from "react";
import type { AsyaContextValue } from "../types";

export const AsyaContext = createContext<AsyaContextValue | null>(null);

export function useAsya(): AsyaContextValue {
  const ctx = useContext(AsyaContext);
  if (!ctx) {
    throw new Error("useAsya() must be used within an AsyaProvider");
  }
  return ctx;
}
