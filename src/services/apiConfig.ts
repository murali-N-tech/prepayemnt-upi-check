// Service to manage dynamic backend server URL for Capacitor Mobile & Web

const STORAGE_KEY = "edge_upi_backend_url";
const MODE_KEY = "edge_upi_backend_mode"; // 'online' | 'offline'

export function isCapacitorNative(): boolean {
  return typeof (window as any).Capacitor !== "undefined" && (window as any).Capacitor.isNativePlatform();
}

export function getStoredBackendUrl(): string {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) return saved.trim();
  
  if (isCapacitorNative()) {
    return "https://edge-upi-backend.onrender.com";
  }
  // Standard web app: relative path to use Express server / Vite proxy
  return "";
}

export function setStoredBackendUrl(url: string): void {
  const trimmed = url.trim().replace(/\/$/, "");
  localStorage.setItem(STORAGE_KEY, trimmed);
}

export function getBackendMode(): "online" | "offline" {
  const mode = localStorage.getItem(MODE_KEY);
  return mode === "offline" ? "offline" : "online";
}

export function setBackendMode(mode: "online" | "offline"): void {
  localStorage.setItem(MODE_KEY, mode);
}

export function getApiUrl(endpointPath: string): string {
  let cleanPath = endpointPath.startsWith("/") ? endpointPath : `/${endpointPath}`;
  const baseUrl = getStoredBackendUrl();

  if (!baseUrl) {
    return cleanPath; // Uses Vite proxy / relative path
  }

  // If cleanPath starts with /api/ and baseUrl does not end with /api, remove /api prefix for direct backend calls
  if (cleanPath.startsWith("/api/") && !baseUrl.endsWith("/api")) {
    cleanPath = cleanPath.substring(4);
  }

  // If baseUrl already ends with /api and cleanPath starts with /api
  if (baseUrl.endsWith("/api") && cleanPath.startsWith("/api")) {
    return `${baseUrl}${cleanPath.substring(4)}`;
  }

  return `${baseUrl}${cleanPath}`;
}

export async function testBackendHealth(customUrl?: string): Promise<{ success: boolean; message: string }> {
  const targetBase = customUrl !== undefined ? customUrl.trim().replace(/\/$/, "") : getStoredBackendUrl();
  const testPath = targetBase ? (targetBase.endsWith("/api") ? `${targetBase}/health` : `${targetBase}/health`) : "/api/health";

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);

    const res = await fetch(testPath, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (res.ok) {
      return { success: true, message: "Connected successfully to backend server." };
    }
    return { success: false, message: `Server returned status code ${res.status}` };
  } catch (err: any) {
    if (err.name === "AbortError") {
      return { success: false, message: "Connection timed out after 8 seconds." };
    }
    return { success: false, message: err.message || "Failed to reach server host." };
  }
}
