import { useEffect, useState } from "react";
import { Activity, Database, ShieldAlert, Search } from "lucide-react";
import { Transaction } from "../types";
import { useAuth } from "../context/AuthContext";

export default function SystemMonitor() {
  const { api } = useAuth();
  const [txs, setTxs] = useState<Transaction[]>([]);
  const [drift, setDrift] = useState<string>("Checking...");
  const [health, setHealth] = useState<string>("Checking...");
  const [healthDetail, setHealthDetail] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState<"all" | "risk" | "safe">("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTelemetry = async () => {
    setLoading(true);
    setError(null);
    try {
      const [txsData, driftData, healthData] = await Promise.all([
        api<Transaction[]>("/api/transactions"),
        api<{ drift_status?: string }>("/api/model-drift"),
        api<{ status?: string; model?: string; model_detail?: string | null }>("/api/health"),
      ]);

      setTxs(Array.isArray(txsData) ? txsData : []);
      setDrift(driftData.drift_status || "Model Stable");
      setHealth(healthData.status === "ok" ? "HEALTHY" : "DEGRADED");
      setHealthDetail(healthData.model_detail ?? null);
    } catch (err: any) {
      setError(err.message || "Failed to parse system metrics");
      setHealth("DEGRADED");
      setDrift("Unknown");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTelemetry();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const filteredTxs = txs.filter(t => {
    // Search filter
    const q = searchQuery.toLowerCase();
    const matchesSearch =
      (t.transaction_id ?? "").toLowerCase().includes(q) ||
      (t.sender ?? "").toLowerCase().includes(q) ||
      (t.receiver ?? "").toLowerCase().includes(q);

    // Risk level filter
    const matchesRisk =
      filterType === "all" ||
      (filterType === "risk" && t.risk === 1) ||
      (filterType === "safe" && t.risk === 0);

    return matchesSearch && matchesRisk;
  });

  return (
    <div className="space-y-8 animate-fade-in" id="system-monitor-container">
      {healthDetail && (
        <div className="bg-amber-500/10 border border-amber-500/20 text-warn text-sm rounded-lg p-4">
          {healthDetail}
        </div>
      )}

      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">System Monitor & Diagnostics</h1>
        <p className="text-ink-muted">
          Supervise operational status logs, machine learning model drift parameters, and execute full transaction history analysis.
        </p>
      </div>

      {/* Diagnostics Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6" id="diagnostics-grid">
        <div className="bg-surface border border-line rounded-xl p-5 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-ink-subtle uppercase tracking-wider block">Operational Health</span>
            <span className={`text-2xl font-extrabold block mt-1.5 ${
              health === "HEALTHY" ? "text-ok" : "text-danger"
            }`}>{health}</span>
          </div>
          <div className={`p-3 rounded-lg ${health === "HEALTHY" ? "bg-emerald-500/10 text-ok" : "bg-rose-500/10 text-danger"}`}>
            <Activity className="h-6 w-6" />
          </div>
        </div>

        <div className="bg-surface border border-line rounded-xl p-5 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-ink-subtle uppercase tracking-wider block">ML Model Drift</span>
            <span className={`text-2xl font-extrabold block mt-1.5 ${
              drift === "Model Stable" ? "text-ok" : "text-warn"
            }`}>{drift}</span>
          </div>
          <div className={`p-3 rounded-lg ${drift === "Model Stable" ? "bg-emerald-500/10 text-ok" : "bg-amber-500/10 text-warn"}`}>
            <ShieldAlert className="h-6 w-6" />
          </div>
        </div>

        <div className="bg-surface border border-line rounded-xl p-5 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-ink-subtle uppercase tracking-wider block">Telemetry Logs</span>
            <span className="text-2xl font-extrabold text-ink block mt-1.5">{txs.length} total txs</span>
          </div>
          <div className="p-3 bg-indigo-500/10 text-brand rounded-lg">
            <Database className="h-6 w-6" />
          </div>
        </div>
      </div>

      {/* Transaction Logs Table Card */}
      <div className="bg-surface border border-line rounded-xl p-6 space-y-6" id="database-logs-card">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <h2 className="text-xl font-semibold text-ink">Processed Transactions Database</h2>

          <div className="flex flex-col sm:flex-row items-stretch gap-3">
            {/* Search inputs */}
            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-ink-subtle" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search Sender/Receiver..."
                className="pl-9 pr-4 py-2 w-full sm:w-60 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500 font-sans"
              />
            </div>

            {/* Select filter */}
            <select
              value={filterType}
              onChange={(e: any) => setFilterType(e.target.value)}
              className="px-3 py-2 bg-inset border border-line rounded-lg text-ink-muted text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="all">All Records</option>
              <option value="risk">Flagged / blocked Only</option>
              <option value="safe">Conforming Only</option>
            </select>
          </div>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 text-danger rounded-lg p-3 text-sm">
            {error}
          </div>
        )}

        {/* Database Grid / Table */}
        <div className="overflow-x-auto border border-line rounded-lg bg-inset">
          <table className="w-full text-left border-collapse text-sm text-ink-muted font-sans">
            <thead>
              <tr className="border-b border-line bg-surface/50 text-ink-muted font-semibold text-xs uppercase">
                <th className="py-3 px-4">Transaction ID</th>
                <th className="py-3 px-4">Amount</th>
                <th className="py-3 px-4">Sender</th>
                <th className="py-3 px-4">Receiver</th>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Scores (Dev/Loc/Vel)</th>
                <th className="py-3 px-4">Decision</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-ink-subtle">
                    <div className="h-6 w-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                    Fetching database logs...
                  </td>
                </tr>
              ) : filteredTxs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-ink-subtle">
                    No transaction entries found matching query filters.
                  </td>
                </tr>
              ) : (
                filteredTxs.map((t, idx) => (
                  <tr key={idx} className="border-b border-line hover:bg-surface/30 font-mono text-xs">
                    <td className="py-3 px-4 text-brand font-semibold">{t.transaction_id}</td>
                    <td className="py-3 px-4 text-ink font-bold">₹{t.amount}</td>
                    <td className="py-3 px-4">{t.sender}</td>
                    <td className="py-3 px-4">{t.receiver || "-"}</td>
                    <td className="py-3 px-4 text-ink-subtle">{t.timestamp}</td>
                    <td className="py-3 px-4 text-ink-muted">
                      {t.device_score.toFixed(2)} / {t.location_score.toFixed(2)} / {t.velocity_score}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`px-2.5 py-0.5 rounded font-sans font-bold text-[10px] uppercase border ${
                        t.risk === 1 
                          ? "bg-rose-500/10 border-rose-500/20 text-danger" 
                          : "bg-emerald-500/10 border-emerald-500/20 text-ok"
                      }`}>
                        {t.risk === 1 ? "BLOCKED" : "APPROVED"}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
