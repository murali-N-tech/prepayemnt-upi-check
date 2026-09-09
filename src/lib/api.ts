import { getApiUrl } from "../services/apiConfig";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export type ApiFetch = <T>(path: string, init?: RequestInit) => Promise<T>;

/**
 * Builds a fetch wrapper that attaches the bearer token, parses JSON, and
 * turns a 401 into a sign-out instead of leaving the UI in a logged-in shell
 * whose every request silently fails.
 */
export function createApi(token: string | null, onUnauthorized: () => void): ApiFetch {
  return async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    // Relative in the browser (Vite proxy in dev, Vercel rewrite in prod),
    // absolute in the Android build where there is no same-origin server.
    const res = await fetch(getApiUrl(path), { ...init, headers });

    if (res.status === 401) {
      onUnauthorized();
      throw new ApiError(401, "Your session has expired. Please sign in again.");
    }

    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }

    if (!res.ok) {
      const d = data as { detail?: string; error?: string; details?: string } | null;
      throw new ApiError(
        res.status,
        d?.details ?? d?.detail ?? d?.error ?? `Request failed (${res.status})`
      );
    }

    return data as T;
  };
}
