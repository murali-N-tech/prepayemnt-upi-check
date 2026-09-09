import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Server, CheckCircle2, AlertTriangle, Wifi, WifiOff, Smartphone, X, Loader2, Globe } from "lucide-react";
import { getStoredBackendUrl, setStoredBackendUrl, testBackendHealth, isCapacitorNative, getBackendMode, setBackendMode } from "../services/apiConfig";

interface BackendSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function BackendSettingsModal({ isOpen, onClose }: BackendSettingsModalProps) {
  const [url, setUrl] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [mode, setMode] = useState<"online" | "offline">("online");

  useEffect(() => {
    if (isOpen) {
      setUrl(getStoredBackendUrl());
      setMode(getBackendMode());
      setTestResult(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    const res = await testBackendHealth(url);
    setTestResult(res);
    setTesting(false);
  };

  const handleSave = () => {
    setStoredBackendUrl(url);
    setBackendMode(mode);
    onClose();
    window.location.reload(); // Apply new backend endpoint configuration
  };

  // Rendered into <body>. The header this is opened from carries a
  // backdrop-blur, and a backdrop-filter creates a containing block for
  // fixed-position descendants - so `fixed inset-0` resolved to the 64px
  // header and the dialog was clipped to a sliver.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-surface border border-line rounded-2xl max-w-md w-full max-h-[90vh] overflow-y-auto p-6 shadow-lift space-y-6 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 text-ink-muted hover:text-ink bg-raised/50 rounded-lg transition"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="flex items-center gap-3">
          <div className="p-3 bg-indigo-500/10 text-brand rounded-xl">
            <Server className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-ink">Mobile Backend Settings</h2>
            <p className="text-xs text-ink-muted">Configure Capacitor native app & server endpoint</p>
          </div>
        </div>

        {/* Runtime platform badge */}
        <div className="bg-inset border border-line rounded-xl p-3 flex items-center justify-between text-xs font-mono">
          <span className="text-ink-muted flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-brand" /> Platform Environment
          </span>
          <span className={`px-2.5 py-0.5 rounded font-bold uppercase ${isCapacitorNative() ? "bg-purple-500/20 text-purple-300 border border-purple-500/30" : "bg-emerald-500/20 text-ok border border-emerald-500/30"}`}>
            {isCapacitorNative() ? "Capacitor Mobile Native" : "Standard Web App"}
          </span>
        </div>

        {/* Engine mode toggle */}
        <div className="space-y-2">
          <label className="block text-xs font-semibold text-ink-muted uppercase tracking-wider">Execution Mode</label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setMode("online")}
              className={`p-3 rounded-xl border text-xs font-bold transition flex flex-col items-center gap-1.5 cursor-pointer ${
                mode === "online"
                  ? "bg-brand/12 border-brand text-brand"
                  : "bg-inset border-line text-ink-muted hover:text-ink"
              }`}
            >
              <Wifi className="h-5 w-5 text-brand" />
              Backend Server Online
            </button>

            <button
              type="button"
              onClick={() => setMode("offline")}
              className={`p-3 rounded-xl border text-xs font-bold transition flex flex-col items-center gap-1.5 cursor-pointer ${
                mode === "offline"
                  ? "bg-warn/12 border-warn text-warn"
                  : "bg-inset border-line text-ink-muted hover:text-ink"
              }`}
            >
              <WifiOff className="h-5 w-5 text-warn" />
              Mobile Offline Engine
            </button>
          </div>
        </div>

        {/* URL input */}
        {mode === "online" && (
          <div className="space-y-3">
            <label className="block text-xs font-semibold text-ink-muted uppercase tracking-wider">
              Backend Server Endpoint Host
            </label>
            <div className="relative">
              <Globe className="absolute left-3 top-2.5 h-4 w-4 text-ink-subtle" />
              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://edge-upi-backend.onrender.com"
                className="w-full pl-9 pr-4 py-2 bg-inset border border-line rounded-lg text-ink font-mono text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <p className="text-[11px] text-ink-subtle">
              Default remote backend: <code className="text-brand bg-inset px-1 py-0.5 rounded">https://edge-upi-backend.onrender.com</code>
            </p>

            <button
              type="button"
              onClick={handleTest}
              disabled={testing}
              className="w-full py-2 px-3 bg-raised hover:bg-raised text-ink font-medium rounded-lg text-xs transition flex items-center justify-center gap-2 cursor-pointer"
            >
              {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Server className="h-4 w-4" />}
              Test Server Connection
            </button>

            {testResult && (
              <div
                className={`p-3 rounded-lg border text-xs flex items-center gap-2 ${
                  testResult.success
                    ? "bg-emerald-500/10 border-emerald-500/20 text-ok"
                    : "bg-rose-500/10 border-rose-500/20 text-danger"
                }`}
              >
                {testResult.success ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
                <span>{testResult.message}</span>
              </div>
            )}
          </div>
        )}

        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 py-2.5 px-4 bg-inset hover:bg-raised border border-line text-ink-muted rounded-xl text-xs font-semibold transition cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="flex-1 py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold shadow-sm transition cursor-pointer"
          >
            Save Settings
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
