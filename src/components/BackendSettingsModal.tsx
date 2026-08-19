import React, { useState, useEffect } from "react";
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-6 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 text-slate-400 hover:text-white bg-slate-800/50 rounded-lg transition"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="flex items-center gap-3">
          <div className="p-3 bg-indigo-500/10 text-indigo-400 rounded-xl">
            <Server className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Mobile Backend Settings</h2>
            <p className="text-xs text-slate-400">Configure Capacitor native app & server endpoint</p>
          </div>
        </div>

        {/* Runtime platform badge */}
        <div className="bg-slate-950 border border-slate-800 rounded-xl p-3 flex items-center justify-between text-xs font-mono">
          <span className="text-slate-400 flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-indigo-400" /> Platform Environment
          </span>
          <span className={`px-2.5 py-0.5 rounded font-bold uppercase ${isCapacitorNative() ? "bg-purple-500/20 text-purple-300 border border-purple-500/30" : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"}`}>
            {isCapacitorNative() ? "Capacitor Mobile Native" : "Standard Web App"}
          </span>
        </div>

        {/* Engine mode toggle */}
        <div className="space-y-2">
          <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">Execution Mode</label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setMode("online")}
              className={`p-3 rounded-xl border text-xs font-bold transition flex flex-col items-center gap-1.5 cursor-pointer ${
                mode === "online"
                  ? "bg-indigo-600/20 border-indigo-500 text-white"
                  : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              <Wifi className="h-5 w-5 text-indigo-400" />
              Backend Server Online
            </button>

            <button
              type="button"
              onClick={() => setMode("offline")}
              className={`p-3 rounded-xl border text-xs font-bold transition flex flex-col items-center gap-1.5 cursor-pointer ${
                mode === "offline"
                  ? "bg-amber-600/20 border-amber-500 text-white"
                  : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              <WifiOff className="h-5 w-5 text-amber-400" />
              Mobile Offline Engine
            </button>
          </div>
        </div>

        {/* URL input */}
        {mode === "online" && (
          <div className="space-y-3">
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
              Backend Server Endpoint Host
            </label>
            <div className="relative">
              <Globe className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://edge-upi-backend.onrender.com"
                className="w-full pl-9 pr-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <p className="text-[11px] text-slate-500">
              Default remote backend: <code className="text-indigo-400 bg-slate-950 px-1 py-0.5 rounded">https://edge-upi-backend.onrender.com</code>
            </p>

            <button
              type="button"
              onClick={handleTest}
              disabled={testing}
              className="w-full py-2 px-3 bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium rounded-lg text-xs transition flex items-center justify-center gap-2 cursor-pointer"
            >
              {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Server className="h-4 w-4" />}
              Test Server Connection
            </button>

            {testResult && (
              <div
                className={`p-3 rounded-lg border text-xs flex items-center gap-2 ${
                  testResult.success
                    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                    : "bg-rose-500/10 border-rose-500/20 text-rose-400"
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
            className="flex-1 py-2.5 px-4 bg-slate-950 hover:bg-slate-800 border border-slate-800 text-slate-400 rounded-xl text-xs font-semibold transition cursor-pointer"
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
    </div>
  );
}
