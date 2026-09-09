import { useEffect, useState } from "react";

export interface Health {
  status: "ok" | "degraded";
  express: string;
  backend: string;
  model: string;
  model_detail: string | null;
  trained_with: Record<string, string> | null;
}

/** Polls the health endpoint that answers for BOTH processes.
 *
 * The old header showed a hardcoded green dot next to the username, which
 * stayed green with the Python service down and every real feature broken.
 * A status light that cannot turn red is decoration, not a status light.
 */
export function useHealth(intervalMs = 30_000): Health | null {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const res = await fetch("/api/health");
        const body = (await res.json()) as Health;
        if (!cancelled) setHealth(body);
      } catch {
        if (!cancelled) {
          setHealth({
            status: "degraded",
            express: "unreachable",
            backend: "unreachable",
            model: "unknown",
            model_detail: "The app server is not responding.",
            trained_with: null,
          });
        }
      }
    };

    poll();
    const timer = setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return health;
}
