import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { PayeeCheckResult } from "../types";

/**
 * The last payee check the person ran, shared with the assistant.
 *
 * The assistant needs to answer "why was this blocked?" about the result on
 * screen, and that result lives inside PayeeCheck's own state. Rather than lift
 * the whole check into App, only the finished result is published here — the
 * assistant reads it, nothing writes back, and no other component depends on it.
 *
 * It is held in memory only. The result includes the payee's address and the
 * amount, which is exactly the sort of thing that should not be sitting in
 * localStorage after the person closes the tab.
 */

interface CheckStore {
  lastCheck: PayeeCheckResult | null;
  setLastCheck: (r: PayeeCheckResult | null) => void;
}

const Ctx = createContext<CheckStore>({ lastCheck: null, setLastCheck: () => {} });

export function CheckProvider({ children }: { children: ReactNode }) {
  const [lastCheck, setLastCheck] = useState<PayeeCheckResult | null>(null);
  const value = useMemo(() => ({ lastCheck, setLastCheck }), [lastCheck]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLastCheck() {
  return useContext(Ctx);
}
