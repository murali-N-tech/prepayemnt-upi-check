import React, { useEffect, useState } from "react";
import {
  AlertOctagon, CheckCircle, ShieldAlert, Calendar, IndianRupee,
  ArrowRight, RefreshCw, Search, FileText, Activity, ShieldCheck, AlertTriangle
} from "lucide-react";
import { Transaction } from "../types";
import { getApiUrl } from "../services/apiConfig";

export default function FraudAlerts() {
  const [alerts, setAlerts] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "statement" | "system">("all");

  const fetchAlerts = async () => {
    setLoading(true);
    setError(null);
    try {
      // Try /api/fraud-alerts first, fallback to /api/transactions
      let res = await fetch(getApiUrl("/api/fraud-alerts"));
      let data: Transaction[] = [];

      if (res.ok) {
        data = await res.json();
      } else {
        res = await fetch(getApiUrl("/api/transactions"));
        if (!res.ok) {
          throw new Error("Unable to read security logs from backend server");
        }
        const allData: Transaction[] = await res.json();
        data = allData.filter(t => t.risk === 1);
      }

      setAlerts(data);
    } catch (err: any) {
      setError(err.message || "Something went wrong fetching fraud alerts");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  // Filtered alerts logic
  const safeAlerts = Array.isArray(alerts) ? alerts : [];
  const filteredAlerts = safeAlerts.filter(a => {
    // Source filter
    if (sourceFilter === "statement") {
      const src = (a.source_type || "").toLowerCase();
      if (src !== "pdf" && src !== "csv" && src !== "statement") return false;
    } else if (sourceFilter === "system") {
      const src = (a.source_type || "").toLowerCase();
      if (src === "pdf" || src === "csv" || src === "statement") return false;
    }

    // Search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const sender = (a.sender || "").toLowerCase();
      const receiver = (a.receiver || "").toLowerCase();
      const upi = (a.upi_id || "").toLowerCase();
      const id = (a.transaction_id || "").toLowerCase();
      const reason = (a.reason || "").toLowerCase();
      return (
        sender.includes(q) ||
        receiver.includes(q) ||
        upi.includes(q) ||
        id.includes(q) ||
        reason.includes(q) ||
        a.amount.toString().includes(q)
      );
    }

    return true;
  });

  // Calculate summary metrics
  const totalThreatAmount = alerts.reduce((sum, a) => sum + (a.amount || 0), 0);
  const statementAlertsCount = alerts.filter(a => {
    const src = (a.source_type || "").toLowerCase();
    return src === "pdf" || src === "csv" || src === "statement";
  }).length;
  const systemAlertsCount = alerts.length - statementAlertsCount;
  const maxThreatAmount = alerts.length > 0 ? Math.max(...alerts.map(a => a.amount || 0)) : 0;

  const formatCurrency = (val: number) => {
    return val.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  };

  const getSourceBadge = (srcType?: string) => {
    const src = (srcType || "system").toLowerCase();
    if (src === "pdf") {
      return (
        <span className="inline-flex items-center gap-1 font-mono text-[10px] font-bold text-purple-400 bg-purple-500/10 border border-purple-500/30 px-2 py-0.5 rounded">
          <FileText className="h-3 w-3" /> PDF STATEMENT
        </span>
      );
    }
    if (src === "csv") {
      return (
        <span className="inline-flex items-center gap-1 font-mono text-[10px] font-bold text-sky-400 bg-sky-500/10 border border-sky-500/30 px-2 py-0.5 rounded">
          <FileText className="h-3 w-3" /> CSV STATEMENT
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 font-mono text-[10px] font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded">
        <Activity className="h-3 w-3" /> LIVE UPI STREAM
      </span>
    );
  };

  return (
    <div className="space-y-8 animate-fade-in" id="fraud-alerts-container">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white mb-2 flex items-center gap-3">
            Real-Time Fraud Alerts
            <span className="px-2.5 py-0.5 bg-rose-500/20 border border-rose-500/30 text-rose-400 text-xs font-mono rounded-full">
              INR (₹) LIVE
            </span>
          </h1>
          <p className="text-slate-400">
            Monitors real-time payment transactions and behavioral threat anomalies extracted from uploaded bank statements (CSV/PDF) and live channels.
          </p>
        </div>

        <button
          onClick={fetchAlerts}
          disabled={loading}
          className="self-start md:self-auto px-4 py-2 bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-white rounded-lg text-sm font-medium transition flex items-center gap-2 cursor-pointer"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin text-rose-400" : ""}`} />
          Refresh Stream
        </button>
      </div>

      {/* KPI Metrics Summary Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" id="fraud-metrics-strip">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 relative overflow-hidden">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">Total Blocked Threats</div>
          <div className="text-2xl font-black text-rose-500 mt-2 flex items-center gap-1">
            <IndianRupee className="h-5 w-5" />
            {formatCurrency(totalThreatAmount)}
          </div>
          <div className="text-xs text-slate-400 mt-1 font-mono">{alerts.length} total flagged transactions</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 relative overflow-hidden">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">Extracted Statement Alerts</div>
          <div className="text-2xl font-black text-purple-400 mt-2 flex items-center gap-1">
            <FileText className="h-5 w-5" />
            {statementAlertsCount} Alerts
          </div>
          <div className="text-xs text-slate-400 mt-1">From uploaded CSV/PDF statements</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 relative overflow-hidden">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">Live Stream Alerts</div>
          <div className="text-2xl font-black text-emerald-400 mt-2 flex items-center gap-1">
            <Activity className="h-5 w-5" />
            {systemAlertsCount} Alerts
          </div>
          <div className="text-xs text-slate-400 mt-1">Real-time payment channel blocks</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 relative overflow-hidden">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">Peak Threat Value</div>
          <div className="text-2xl font-black text-amber-400 mt-2 flex items-center gap-1">
            <IndianRupee className="h-5 w-5" />
            {formatCurrency(maxThreatAmount)}
          </div>
          <div className="text-xs text-slate-400 mt-1">Single maximum risk transfer</div>
        </div>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
        {/* Filter Tabs */}
        <div className="flex items-center gap-2 w-full sm:w-auto overflow-x-auto pb-1 sm:pb-0">
          <button
            onClick={() => setSourceFilter("all")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition whitespace-nowrap cursor-pointer ${
              sourceFilter === "all"
                ? "bg-rose-500 text-white shadow-sm"
                : "bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800"
            }`}
          >
            All Threat Alerts ({alerts.length})
          </button>

          <button
            onClick={() => setSourceFilter("statement")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition whitespace-nowrap cursor-pointer ${
              sourceFilter === "statement"
                ? "bg-purple-600 text-white shadow-sm"
                : "bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800"
            }`}
          >
            Extracted CSV/PDF Statements ({statementAlertsCount})
          </button>

          <button
            onClick={() => setSourceFilter("system")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition whitespace-nowrap cursor-pointer ${
              sourceFilter === "system"
                ? "bg-emerald-600 text-white shadow-sm"
                : "bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800"
            }`}
          >
            Live Payments ({systemAlertsCount})
          </button>
        </div>

        {/* Search input */}
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search sender, merchant, UTR..."
            className="w-full pl-9 pr-4 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-white text-xs placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-rose-500"
          />
        </div>
      </div>

      {/* Main Alerts Feed */}
      {loading ? (
        <div className="flex flex-col items-center justify-center p-16 space-y-3">
          <div className="h-10 w-10 border-2 border-rose-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-slate-400 text-sm">Evaluating live security feeds & extracted statements...</p>
        </div>
      ) : error ? (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-xl p-6 flex items-center gap-3">
          <AlertTriangle className="h-6 w-6 shrink-0" />
          <div>
            <h4 className="font-bold">Error Fetching Alerts</h4>
            <p className="text-xs text-rose-300/80 mt-0.5">{error}</p>
          </div>
        </div>
      ) : filteredAlerts.length === 0 ? (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center max-w-2xl mx-auto space-y-3">
          <ShieldCheck className="h-12 w-12 text-emerald-400 mx-auto opacity-80" />
          <h3 className="text-lg font-semibold text-white">No Flagged Alerts Found</h3>
          <p className="text-slate-400 text-xs">
            {searchQuery || sourceFilter !== "all"
              ? "No fraud alerts match the selected query or filter criteria."
              : "No transactions currently match threat profile rules. Upload a statement in 'Upload Statement' page to test real-time parsing."}
          </p>
        </div>
      ) : (
        <div className="space-y-4 max-w-5xl" id="alerts-stream">
          {filteredAlerts.map((alert, idx) => (
            <div
              key={alert.transaction_id || idx}
              className="bg-slate-900 border border-rose-500/20 hover:border-rose-500/40 rounded-xl p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 transition relative overflow-hidden group shadow-lg"
            >
              {/* Left threat accent line */}
              <div className="absolute top-0 bottom-0 left-0 w-1.5 bg-rose-500 group-hover:bg-rose-400 transition" />

              <div className="flex items-start gap-4">
                <div className="p-3 bg-rose-500/10 text-rose-400 rounded-xl shrink-0 mt-1">
                  <AlertOctagon className="h-6 w-6" />
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-[10px] font-extrabold text-rose-400 bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 rounded uppercase tracking-wider">
                      BLOCK TRIGGERED
                    </span>

                    {getSourceBadge(alert.source_type)}

                    <span className="text-xs text-slate-500 font-mono">
                      Ref: {alert.transaction_id}
                    </span>
                  </div>

                  {/* Sender -> Receiver */}
                  <div className="flex items-center gap-2 text-base font-bold text-white flex-wrap">
                    <span className="font-mono text-indigo-300">{alert.sender}</span>
                    <ArrowRight className="h-4 w-4 text-slate-500 shrink-0" />
                    <span className="font-semibold text-slate-200">{alert.receiver || "Unnamed Receiver"}</span>
                    {alert.upi_id && (
                      <span className="text-xs font-mono text-slate-500 font-normal">
                        ({alert.upi_id})
                      </span>
                    )}
                  </div>

                  {/* Reasons / Anomaly Tags */}
                  {alert.reason && (
                    <div className="text-xs text-rose-300/90 font-medium flex items-center gap-1.5 bg-rose-500/5 border border-rose-500/10 px-2.5 py-1 rounded-md w-fit">
                      <AlertTriangle className="h-3.5 w-3.5 text-rose-400 shrink-0" />
                      <span>{alert.reason}</span>
                    </div>
                  )}

                  {/* Timestamp & Metrics */}
                  <div className="flex items-center gap-4 text-xs text-slate-500 pt-0.5">
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" />
                      {alert.timestamp}
                    </span>
                    <span className="flex items-center gap-1">
                      <ShieldAlert className="h-3.5 w-3.5 text-rose-400" />
                      Velocity Score: {alert.velocity_score}
                    </span>
                    {alert.status && alert.status !== "SUCCESS" && (
                      <span className="font-mono font-bold text-rose-400 uppercase">
                        Status: {alert.status}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Right Side: Amount in INR & Threat Score */}
              <div className="flex md:flex-col items-end gap-3 md:gap-1.5 shrink-0 self-stretch md:self-auto justify-between md:justify-center border-t border-slate-800 md:border-t-0 pt-3 md:pt-0">
                <div className="flex items-center text-2xl font-black text-rose-500 tracking-tight">
                  <IndianRupee className="h-6 w-6 -mr-0.5 stroke-[2.5]" />
                  <span>{formatCurrency(alert.amount)}</span>
                </div>

                <div className="text-right">
                  <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">Threat Score</span>
                  <span className="text-sm font-black text-rose-400 font-mono bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 rounded">
                    {alert.risk_score}/100
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
